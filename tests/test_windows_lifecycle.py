# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import struct
import unittest

from tools.extract_windows_classifier import PROJECT_CONFIG_OFFSET
from tools.extract_windows_lifecycle import (
    BaseClassHistory,
    CLASS_COUNT,
    ContextWindow,
    OLD_CLASS_COUNT,
    OutputOverrideInput,
    ProjectLifecycle,
    TRANSITION_STRIDE,
    TRANSITION_TABLE_OFFSET,
    apply_output_code_override,
)


def make_lifecycle_dll(project_id: int = 0x0C83) -> bytes:
    blob_length = 0x2000
    blob = bytearray(blob_length)
    blob[0:4] = b"PSDB"
    struct.pack_into("<HH", blob, 4, 4, project_id)
    struct.pack_into("<I", blob, 0x18, blob_length)
    table = PROJECT_CONFIG_OFFSET + TRANSITION_TABLE_OFFSET
    struct.pack_into("<B3xff", blob, PROJECT_CONFIG_OFFSET + 0x8D8, 1, 5.0, 14.0)
    struct.pack_into("<4H", blob, PROJECT_CONFIG_OFFSET + 0xDE4, 0, 6, 4, 4)
    struct.pack_into(
        "<4H", blob, PROJECT_CONFIG_OFFSET + 0xDF4, 20, 9999, 50, 100
    )
    struct.pack_into("<HH", blob, PROJECT_CONFIG_OFFSET + 0xE78, 300, 300)
    struct.pack_into("<BBB", blob, PROJECT_CONFIG_OFFSET + 0xE98, 1, 1, 10)
    struct.pack_into("<f", blob, 0xB90, 36.0)
    struct.pack_into("<f", blob, 0xB98, 0.0)
    struct.pack_into("<fff", blob, PROJECT_CONFIG_OFFSET + 0xE00, -17.0, -10.0, 215.0)
    struct.pack_into(
        "<bBBBBbbbbB",
        blob,
        PROJECT_CONFIG_OFFSET + 0xE0C,
        2,
        6,
        8,
        35,
        10,
        6,
        -10,
        -10,
        0,
        4,
    )
    for old_class in range(OLD_CLASS_COUNT):
        for new_class in range(CLASS_COUNT):
            index = new_class + old_class * CLASS_COUNT
            record = table + index * TRANSITION_STRIDE
            struct.pack_into("<I", blob, record, CLASS_COUNT)
            struct.pack_into("<4i", blob, record + 0x04, 20, 0, 10, 30)
            struct.pack_into("<I", blob, record + 0x14, CLASS_COUNT)
            struct.pack_into("<4i", blob, record + 0x18, 100, 0, 10, 30)
            struct.pack_into("<h", blob, record + 0x28, -500)
            struct.pack_into("<bBBBBB", blob, record + 0x2A, 2, 5, 3, 1, 2, 0)
    # This field is also the absolute floor in the final transition record.
    struct.pack_into("<h", blob, PROJECT_CONFIG_OFFSET + 0xCB4, -20)
    return bytes(blob)


class WindowsLifecycleTests(unittest.TestCase):
    def test_extracts_transition_fields_and_matrix_order(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        rule = lifecycle.rule(2, 1)
        self.assertEqual((rule.old_class, rule.new_class), (2, 1))
        self.assertEqual(rule.history_score_margins, (20, 0, 10, 30))
        self.assertEqual(rule.current_score_margins, (100, 0, 10, 30))
        self.assertEqual(rule.absolute_score_min, -500)
        self.assertEqual(rule.context_score_bias, 2)
        self.assertEqual(rule.history_depth, 5)
        self.assertEqual(rule.initial_age_limit, 3)
        self.assertTrue(rule.context_allowed)
        self.assertEqual(rule.context_extra_history, 2)
        self.assertEqual(rule.required_history(), 5)
        self.assertEqual(rule.required_history(extra_context=True), 7)
        self.assertTrue(lifecycle.special_single_pair_matching)
        self.assertEqual(lifecycle.normal_match_radius, 5.0)
        self.assertEqual(lifecycle.single_pair_match_radius, 14.0)
        self.assertEqual(lifecycle.class_point_count_minimums, (0, 6, 4, 4))
        self.assertEqual(lifecycle.class_point_count_maximums, (20, 9999, 50, 100))
        self.assertEqual(lifecycle.context_window_frames, 300)
        self.assertTrue(lifecycle.context_source_resets_window)
        self.assertTrue(lifecycle.context_regions_enabled)
        self.assertEqual(lifecycle.context_region_distance, 10)
        self.assertEqual(lifecycle.output_merge_squared_limit, 36.0)
        self.assertEqual(lifecycle.output_merge_disabled_limit, 0.0)
        self.assertEqual(lifecycle.override_score2_floor_without_pen, -17.0)
        self.assertEqual(lifecycle.override_score2_floor_with_pen, -10.0)
        self.assertEqual(lifecycle.override_pen_distance_squared, 215.0)
        self.assertEqual(lifecycle.override_context_age_adjustment, 2)
        self.assertEqual(lifecycle.override_age_minimum, 6)
        self.assertEqual(lifecycle.override_age_maximum, 8)
        self.assertEqual(lifecycle.override_force_age, 35)
        self.assertEqual(lifecycle.override_force_counter, 10)
        self.assertEqual(lifecycle.override_candidate_margin, 6)
        self.assertEqual(lifecycle.override_default_margin, -10)
        self.assertEqual(lifecycle.override_context_margin, -10)
        self.assertEqual(lifecycle.override_pen_margin, 0)
        self.assertEqual(lifecycle.override_minimum_counter, 4)
        self.assertEqual(lifecycle.override_score3_floor, -20)

    def test_output_override_history_branch_changes_code_four_to_two(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        previous = ((0.0, -20.0, 0.0, -30.0),) * 5
        decision = apply_output_code_override(
            lifecycle,
            OutputOverrideInput(
                age=6,
                original_code=4,
                current_scores=(0.0, 0.0, 0.0, 0.0),
                previous_scores_newest_first=previous,
                counter_254=4,
                metric_54=4.0,
                level_signal=0.12,
            ),
        )
        self.assertEqual(decision.code, 2)
        self.assertEqual(decision.triggered, ("history_code2",))

    def test_output_override_two_low_samples_can_overwrite_code_two(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        previous = ((-100.0, -100.0, -100.0, -20.0),) * 5
        decision = apply_output_code_override(
            lifecycle,
            OutputOverrideInput(
                age=6,
                original_code=4,
                current_scores=(-100.0, -100.0, -100.0, -20.0),
                previous_scores_newest_first=previous,
                counter_254=4,
                metric_54=4.0,
                level_signal=0.12,
            ),
        )
        self.assertEqual(decision.code, 1)
        self.assertEqual(decision.triggered, ("two_low_samples_code1",))

    def test_output_override_age_counter_is_strict_and_not_code_four_only(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        at_boundary = apply_output_code_override(
            lifecycle,
            OutputOverrideInput(
                age=35,
                original_code=2,
                current_scores=(0.0, 0.0, 0.0, 0.0),
                previous_scores_newest_first=(),
                counter_250=10,
            ),
        )
        self.assertEqual(at_boundary.code, 2)
        after_boundary = apply_output_code_override(
            lifecycle,
            OutputOverrideInput(
                age=36,
                original_code=2,
                current_scores=(0.0, 0.0, 0.0, 0.0),
                previous_scores_newest_first=(),
                counter_250=10,
            ),
        )
        self.assertEqual(after_boundary.code, 1)
        self.assertEqual(after_boundary.triggered, ("age_counter_code1",))

    def test_extracts_unclassified_new_track_row(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        rule = lifecycle.rule(4, 0)
        self.assertEqual((rule.old_class, rule.new_class), (4, 0))
        with self.assertRaisesRegex(ValueError, "old class"):
            lifecycle.rule(5, 0)

    def test_current_score_gate_matches_windows_inequalities(self):
        rule = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83).rule(0, 1)
        self.assertTrue(rule.passes_current_scores((0, 120, 100, 90)))
        self.assertFalse(rule.passes_current_scores((21, 120, 100, 90)))
        # Equality is accepted because Windows rejects only a strict deficit.
        self.assertTrue(rule.passes_current_scores((20, 120, 110, 90)))
        self.assertFalse(
            rule.passes_current_scores(
                (20, 120, 110, 90), comparison_bias=1
            )
        )
        self.assertFalse(
            rule.passes_current_scores(
                (0, -480, -500, -510), absolute_min_override=-479
            )
        )

    def test_history_gate_requires_every_selected_sample(self):
        rule = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83).rule(0, 1)
        passing = [(0, 50, 40, 20)] * 5
        self.assertTrue(rule.passes_score_history(passing))
        self.assertFalse(rule.passes_score_history(passing[:4]))
        failing = list(passing)
        failing[3] = (31, 50, 40, 20)
        self.assertFalse(rule.passes_score_history(failing))
        self.assertFalse(rule.passes_score_history(passing, extra_context=True))

    def test_history_gate_obeys_windows_ten_sample_capacity(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        rule = lifecycle.rule(1, 3)
        object.__setattr__(rule, "history_depth", 30)
        self.assertFalse(rule.passes_score_history([(0, 0, 0, 100)] * 30))

    def test_context_disallowed_rule_rejects_current_gate(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        rule = lifecycle.rule(4, 0)
        object.__setattr__(rule, "context_allowed", False)
        self.assertFalse(rule.passes_current_scores((200, 0, 0, 0), track_context=True))

    def test_base_history_uses_new_track_row_then_history_order(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        history = BaseClassHistory(lifecycle)
        first = history.update((200, 0, 0, 0))
        self.assertEqual((first.previous_class, first.candidate_class), (4, 0))
        self.assertTrue(first.accepted)
        self.assertEqual(first.gate, "current")

        second = history.update((21, 120, 110, 90))
        self.assertFalse(second.accepted)
        self.assertEqual(second.selected_class, 0)
        self.assertEqual(second.gate, "history")

    def test_base_history_applies_class_point_count_range(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        history = BaseClassHistory(lifecycle)
        decision = history.update((200, 0, 0, 0), point_count=21)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.selected_class, 4)
        self.assertEqual(decision.gate, "point_count")
        with self.assertRaisesRegex(ValueError, "point count"):
            BaseClassHistory(lifecycle).update(
                (200, 0, 0, 0), point_count=-1
            )

    def test_same_class_transition_is_stable(self):
        rule = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83).rule(2, 2)
        self.assertTrue(rule.passes_current_scores((0, 0, 0, 0)))
        self.assertTrue(rule.passes_score_history(()))

    def test_context_window_counts_from_arm_scan_and_handles_wrap(self):
        window = ContextWindow(300)
        window.arm(1000)
        decision = window.update(
            1005,
            persistent_flag=False,
            source_active=False,
            frame_flag=False,
            source_resets_window=True,
        )
        self.assertEqual(decision.remaining, 295)
        self.assertTrue(decision.active)

        window.arm(0xFFFE)
        decision = window.update(
            1,
            persistent_flag=False,
            source_active=False,
            frame_flag=False,
            source_resets_window=True,
        )
        self.assertEqual(decision.remaining, 298)

    def test_context_window_inputs_and_expiry_are_exact(self):
        window = ContextWindow(4)
        window.arm(10)
        at_boundary = window.update(
            14,
            persistent_flag=False,
            source_active=False,
            frame_flag=False,
            source_resets_window=False,
        )
        self.assertEqual(at_boundary.remaining, 0)
        self.assertFalse(at_boundary.active)

        reset = window.update(
            20,
            persistent_flag=False,
            source_active=True,
            frame_flag=False,
            source_resets_window=True,
        )
        self.assertEqual(reset.remaining, 4)
        self.assertTrue(reset.active)
        direct = window.update(
            21,
            persistent_flag=True,
            source_active=False,
            frame_flag=False,
            source_resets_window=False,
        )
        self.assertTrue(direct.active)

    def test_rejects_bad_score_lengths_and_truncated_table(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        with self.assertRaisesRegex(ValueError, "expected 4 scores"):
            lifecycle.rule(0, 1).passes_current_scores((1, 2, 3))
        truncated = bytearray(make_lifecycle_dll())
        struct.pack_into("<I", truncated, 0x18, 0x1000)
        with self.assertRaisesRegex(ValueError, "too short"):
            ProjectLifecycle.from_dll(bytes(truncated), 0x0C83)


if __name__ == "__main__":
    unittest.main()
