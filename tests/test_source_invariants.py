# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "phase55" / "modules" / "g6ts_biosref.c"
LIFECYCLE_PROFILE = ROOT / "phase55" / "modules" / "g6ts_lifecycle_profile.h"


def function_body(source: str, name: str) -> str:
    start = source.index(name)
    opening = source.index("{", start)
    depth = 0
    for offset in range(opening, len(source)):
        if source[offset] == "{":
            depth += 1
        elif source[offset] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : offset + 1]
    raise AssertionError(f"unterminated function {name}")


class SourceInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CLIENT.read_text(encoding="utf-8")
        cls.lifecycle_profile = LIFECYCLE_PROFILE.read_text(encoding="utf-8")

    def test_recovery_uses_hardware_validated_minimal_order(self):
        body = function_body(self.source, "g6ts_full_reinitialize_locked")
        ordered = (
            "g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x05",
            "g6ts_dma_feature_exchange(ts, GET_FEATURE, 0x70",
            "g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x70",
            "g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x56",
        )
        positions = [body.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_windows_collection_setup_is_not_replayed_during_recovery(self):
        body = function_body(self.source, "g6ts_full_reinitialize_locked")
        forbidden = (
            "GET_FEATURE, 0x60",
            "OUTPUT_REPORT, 0x65",
            "GET_FEATURE, 0x06",
            "OUTPUT_REPORT, 0x09",
            "GET_FEATURE, 0x73",
        )
        for command in forbidden:
            self.assertNotIn(command, body)

        for removed_symbol in (
            "g6ts_output65",
            "g6ts_output09_a1_template",
            "g6ts_output09_a5_template",
            "g6ts_etw_firmware_version",
        ):
            self.assertNotIn(removed_symbol, self.source)

    def test_assignment_initializes_every_output_slot(self):
        body = function_body(self.source, "g6ts_assign_tracks")
        initialization = body.index("contact_slots[i] = -1")
        early_return = body.index("if (!active_count || !count)")
        self.assertLess(initialization, early_return)

    def test_phase70_policy_is_opt_in_and_read_only(self):
        self.assertIn("static bool g6ts_windows_orchestrator;", self.source)
        self.assertIn(
            "module_param_named(windows_orchestrator, "
            "g6ts_windows_orchestrator, bool, 0444)",
            self.source,
        )

    def test_phase70_assignment_uses_sensor_space_and_strict_radius(self):
        body = function_body(self.source, "g6ts_track_distance")
        for token in (
            "sensor_x_q24",
            "sensor_y_q24",
            "G6TS_WINDOWS_ASSIGN_X_SCALE_Q24",
            "G6TS_WINDOWS_ASSIGN_Y_SCALE_Q24",
            "squared >= G6TS_WINDOWS_ASSIGN_RADIUS",
        ):
            self.assertIn(token, body)

    def test_phase70_direct_coordinates_do_not_use_scalar_smoothing(self):
        body = function_body(self.source, "g6ts_update_track")
        start = body.index("if (g6ts_windows_orchestrator)")
        fallback = body.index("} else {", start)
        windows_branch = body[start:fallback]
        self.assertIn("track->output_x = contact->x", windows_branch)
        self.assertIn("track->output_y = contact->y", windows_branch)
        self.assertNotIn("g6ts_filter_coordinate", windows_branch)

    def test_frame_orchestrator_has_one_ordered_collection_boundary(self):
        body = function_body(self.source, "g6ts_report_heat_contacts")
        ordered = (
            "g6ts_assign_tracks",
            "g6ts_update_track",
            "g6ts_advance_unmatched_tracks",
            "g6ts_create_unmatched_tracks",
            "g6ts_collect_linux_contacts",
        )
        positions = [body.index(token) for token in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("input_sync", body)

    def test_generated_profile_contains_all_twenty_transitions(self):
        self.assertEqual(self.lifecycle_profile.count(" -> "), 20)
        for old_class in range(5):
            for new_class in range(4):
                self.assertIn(
                    f"/* {old_class} -> {new_class} */", self.lifecycle_profile
                )
        self.assertIn("G6TS_WINDOWS_HISTORY_CAPACITY 10U", self.lifecycle_profile)
        self.assertIn("G6TS_WINDOWS_ASSIGN_RADIUS 5U", self.lifecycle_profile)
        self.assertIn(
            "G6TS_WINDOWS_SCORE3_PRIMARY_Q24 838860800LL",
            self.lifecycle_profile,
        )

    def test_windows_score_three_postprocessor_uses_recovered_peak_counts(self):
        peak_body = function_body(self.source, "g6ts_local_peak_counts")
        scorer_body = function_body(self.source, "g6ts_classify_contact")
        for token in (
            "local_peak_count",
            "strong_local_peak_count",
            "G6TS_LOCAL_PEAK_CAPACITY",
            "G6TS_LOCAL_PEAK_FLOOR_Q12",
        ):
            self.assertIn(token, peak_body)
        self.assertIn("G6TS_WINDOWS_SCORE3_PRIMARY_Q24", scorer_body)
        self.assertIn("G6TS_WINDOWS_SCORE3_SINGLE_Q24", scorer_body)


if __name__ == "__main__":
    unittest.main()
