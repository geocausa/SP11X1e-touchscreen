# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "phase55" / "modules" / "mshw0485_touch.c"
LEGACY_CLIENT = ROOT / "src" / "g6ts_biosref.c"
DMA_KBUILD = ROOT / "phase55" / "modules" / "Kbuild"
LIFECYCLE_PROFILE = ROOT / "phase55" / "modules" / "g6ts_lifecycle_profile.h"
ROOT_MAKEFILE = ROOT / "Makefile"
PHASE75_OVERLAY = ROOT / "dts" / "phase75-mshw0485-production.dtso"
PHASE75_DEPLOY = ROOT / "scripts" / "deploy_phase75_identity.sh"
PHASE76_BOOT = ROOT / "boot" / "63_sp11_713_phase76_behavior"
PHASE76_DEPLOY = ROOT / "scripts" / "deploy_phase76_behavior.sh"
PHASE77_BOOT = ROOT / "boot" / "64_sp11_713_phase77_recovery"
PHASE77_DEPLOY = ROOT / "scripts" / "deploy_phase77_recovery.sh"


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
        cls.legacy_source = LEGACY_CLIENT.read_text(encoding="utf-8")
        cls.dma_kbuild = DMA_KBUILD.read_text(encoding="utf-8")
        cls.lifecycle_profile = LIFECYCLE_PROFILE.read_text(encoding="utf-8")
        cls.root_makefile = ROOT_MAKEFILE.read_text(encoding="utf-8")
        cls.phase75_overlay = PHASE75_OVERLAY.read_text(encoding="utf-8")
        cls.phase75_deploy = PHASE75_DEPLOY.read_text(encoding="utf-8")
        cls.phase76_boot = PHASE76_BOOT.read_text(encoding="utf-8")
        cls.phase76_deploy = PHASE76_DEPLOY.read_text(encoding="utf-8")
        cls.phase77_boot = PHASE77_BOOT.read_text(encoding="utf-8")
        cls.phase77_deploy = PHASE77_DEPLOY.read_text(encoding="utf-8")

    def test_default_build_is_the_production_dma_set(self):
        self.assertIn("all: production", self.root_makefile)
        self.assertIn("production: phase55", self.root_makefile)
        self.assertIn("legacy-fifo: phase52", self.root_makefile)

    def test_phase75_dtb_is_reproducible_from_fifo_baseline(self):
        for token in (
            "&spi10",
            "qcom,enable-gsi-dma",
            "dmas = <&gpi_dma1 0 2 4>, <&gpi_dma1 1 2 4>",
            'dma-names = "tx", "rx"',
            'compatible = "microsoft,mshw0485"',
        ):
            self.assertIn(token, self.phase75_overlay)
        self.assertIn("base_fifo_dtb", self.phase75_deploy)
        self.assertNotIn("prebuilt/", self.phase75_deploy)

    def test_production_identity_is_distinct_from_legacy_fifo(self):
        self.assertIn('G6TS_NAME\t\t\t"mshw0485-touch"', self.source)
        self.assertIn('compatible = "microsoft,mshw0485"', self.source)
        self.assertNotIn('compatible = "microsoft,mshw0485-biosref"', self.source)
        self.assertIn("obj-m += mshw0485_touch.o", self.dma_kbuild)
        self.assertNotIn("obj-m += g6ts_biosref.o", self.dma_kbuild)
        self.assertIn('compatible = "microsoft,mshw0485-biosref"',
                      self.legacy_source)

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

    def test_cold_boot_only_setup_is_not_replayed_during_recovery(self):
        body = function_body(self.source, "g6ts_full_reinitialize_locked")
        forbidden = (
            "GET_FEATURE, 0x60",
            "OUTPUT_REPORT, 0x65",
            "GET_FEATURE, 0x06",
            "GET_FEATURE, 0x73",
        )
        for command in forbidden:
            self.assertNotIn(command, body)

        # KDNET proves that report 0x09 belongs to Windows initialization and
        # reset recovery. Phase 72 proves only that the combined Linux sequence
        # containing this short report eliminated the observed reset storm.
        self.assertIn("OUTPUT_REPORT, 0x09", body)

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

    def test_phase76_profile_is_opt_in_and_transport_independent(self):
        self.assertIn("static bool g6ts_behavior_v2;", self.source)
        self.assertIn(
            "module_param_named(behavior_v2, g6ts_behavior_v2, bool, 0444)",
            self.source,
        )
        probe = function_body(self.source, "g6ts_probe")
        self.assertIn(
            "g6ts_behavior_v2 && g6ts_windows_orchestrator", probe
        )
        recovery = function_body(self.source, "g6ts_full_reinitialize_locked")
        self.assertNotIn("g6ts_behavior_v2", recovery)

    def test_phase76_uses_proven_geometry_and_two_frame_gate(self):
        centroid = function_body(self.source, "g6ts_phase76_output_centroid")
        self.assertIn("G6TS_WINDOWS_CENTROID_BASELINE", centroid)
        self.assertIn("contact->output_x", centroid)
        self.assertIn("contact->output_y", centroid)

        distance = function_body(self.source, "g6ts_track_distance")
        self.assertIn(
            "g6ts_windows_orchestrator || g6ts_behavior_v2", distance
        )
        confirmation = function_body(
            self.source, "g6ts_confirmation_requirement"
        )
        self.assertIn("G6TS_BEHAVIOR_CONFIRM_NORMAL", confirmation)

        update = function_body(self.source, "g6ts_update_track")
        phase76 = update[update.index("else if (g6ts_behavior_v2)") :]
        self.assertIn("contact->output_x", phase76)
        self.assertNotIn("g6ts_filter_coordinate", phase76.split("} else {")[0])

    def test_phase76_exposes_read_only_behavior_counters(self):
        show = function_body(self.source, "behavior_stats_show")
        for token in (
            "heat_frames",
            "components",
            "accepted_contacts",
            "assignment_matches",
            "processing_average_ns",
            "panel_resets",
        ):
            self.assertIn(token, show)
        self.assertIn("static DEVICE_ATTR_RO(behavior_stats)", self.source)

    def test_phase76_deployment_is_isolated_from_phase75(self):
        for token in (
            "sp11-phase76-behavior",
            "sp11_entry=7.1.3-phase76-behavior",
            "mshw0485_touch.behavior_v2=1",
        ):
            self.assertIn(token, self.phase76_boot)
        self.assertIn("phase75_assets", self.phase76_deploy)
        self.assertIn("grub-reboot sp11-phase76-behavior", self.phase76_deploy)
        self.assertIn("saved GRUB default remains unchanged", self.phase76_deploy)
        self.assertNotIn("grub-set-default", self.phase76_deploy)

    def test_phase77_software_recovery_is_opt_in_and_gated(self):
        self.assertIn("static bool g6ts_reset_recovery_v2;", self.source)
        self.assertIn(
            "module_param_named(reset_recovery_v2, "
            "g6ts_reset_recovery_v2, bool, 0444)",
            self.source,
        )

        irq = function_body(self.source, "g6ts_interrupt_thread")
        self.assertIn("g6ts_note_panel_reset_locked(ts, true)", irq)
        reset = function_body(self.source, "g6ts_note_panel_reset_locked")
        self.assertIn("G6TS_RECOVERY_SOFTWARE", reset)
        self.assertIn("reset_notifications++", reset)
        self.assertIn("g6ts_release_contacts", reset)
        reader = function_body(self.source, "g6ts_dma_read_response")
        self.assertIn("if (READ_ONCE(ts->mode_enabled))", reader)

        feature = function_body(self.source, "g6ts_dma_feature_exchange")
        expected = function_body(self.source, "g6ts_recovery_read_expected")
        for body in (feature, expected):
            self.assertIn("g6ts_note_panel_reset_locked(ts, false)", body)
            self.assertIn("return -EPIPE", body)

        recovery = function_body(self.source, "g6ts_full_reinitialize_locked")
        hardware = recovery.index("path == G6TS_RECOVERY_HARDWARE")
        power_off = recovery.index("g6ts_power_off", hardware)
        descriptor = recovery.index("g6ts_device_descriptor_cmd")
        verify = recovery.index("g6ts_verify_heat_ready")
        enable = recovery.index("ts->mode_enabled = true")
        self.assertLess(hardware, power_off)
        self.assertLess(power_off, descriptor)
        self.assertLess(descriptor, verify)
        self.assertLess(verify, enable)

        worker = function_body(self.source, "g6ts_recovery_work")
        self.assertIn("software_recovery_fallbacks", worker)
        self.assertIn("G6TS_RECOVERY_HARDWARE", worker)

    def test_phase77_deployment_is_isolated_from_saved_baseline(self):
        for token in (
            "sp11-phase77-recovery",
            "sp11_entry=7.1.3-phase77-recovery",
            "mshw0485_touch.behavior_v2=1",
            "mshw0485_touch.reset_recovery_v2=1",
        ):
            self.assertIn(token, self.phase77_boot)
        self.assertIn("phase75_assets", self.phase77_deploy)
        self.assertIn("grub-reboot sp11-phase77-recovery", self.phase77_deploy)
        self.assertIn("saved GRUB default remains unchanged", self.phase77_deploy)
        self.assertNotIn("grub-set-default", self.phase77_deploy)

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
