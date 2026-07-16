# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import struct
import unittest

from tools.extract_windows_classifier import PROJECT_CONFIG_OFFSET
from tools.extract_windows_lifecycle import (
    BaseClassHistory,
    CLASS_COUNT,
    ContactBounds,
    ContextWindow,
    FingerClassPolicyInput,
    LocalContextInput,
    NeighborBoundsInput,
    OLD_CLASS_COUNT,
    OutputOverrideInput,
    ProjectLifecycle,
    TRANSITION_STRIDE,
    TRANSITION_TABLE_OFFSET,
    adjust_young_track_bounds,
    apply_finger_class_policy,
    apply_output_code_override,
    frame_level_exceeds_limit,
    resolve_local_context,
    uses_fallback_feature_profile,
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
    struct.pack_into("<fH", blob, PROJECT_CONFIG_OFFSET + 0x8E8, 7.5, 100)
    struct.pack_into("<HHB", blob, PROJECT_CONFIG_OFFSET + 0xE66, 100, 215, 0)
    struct.pack_into("<HH", blob, PROJECT_CONFIG_OFFSET + 0xE80, 50, 30)
    # FUN_180049dd0 class-three rule: subtract (-30, 5, 0, -30),
    # enabled, for a current age through three; double after neighbor age ten.
    struct.pack_into(
        "<4hBBB",
        blob,
        PROJECT_CONFIG_OFFSET + 0xD84 + 3 * 0x10,
        -30,
        5,
        0,
        -30,
        1,
        3,
        10,
    )
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
    blob[0x1C84] = 1
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
        self.assertEqual(lifecycle.frame_level_limit, 300)
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
        self.assertEqual(lifecycle.unclassified_code3_level_threshold, 7.5)
        self.assertEqual(lifecycle.unclassified_code3_age_release, 100)
        self.assertEqual(lifecycle.pen_force_age_maximum, 100)
        self.assertEqual(lifecycle.pen_force_distance_squared, 215)
        self.assertFalse(lifecycle.pen_force_enabled)
        self.assertEqual(lifecycle.normal_feature_point_limit, 50)
        self.assertEqual(lifecycle.context_feature_point_limit, 30)
        self.assertTrue(lifecycle.descriptor_context_demotion_enabled)
        self.assertFalse(lifecycle.neighbor_bounds_rules[0].enabled)
        self.assertEqual(
            lifecycle.neighbor_bounds_rules[3].min_x_adjustment, -30
        )
        self.assertEqual(
            lifecycle.neighbor_bounds_rules[3].enclosing_age_double_after, 10
        )

    @staticmethod
    def _override(age: int, old_class: int) -> OutputOverrideInput:
        previous = ()
        if old_class == 4 and age > 2:
            previous = ((0.0, 0.0, 0.0, 0.0),)
        return OutputOverrideInput(
            age=age,
            original_code=old_class,
            current_scores=(0.0, 0.0, 0.0, 0.0),
            previous_scores_newest_first=previous,
        )

    def test_neighbor_bounds_uses_previous_sample_and_strict_enclosure(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        candidate = ContactBounds(10.0, 20.0, 12.0, 22.0)
        neighbor = NeighborBoundsInput(
            state=1,
            age=11,
            current_class=0,
            previous_class=3,
            current_bounds=ContactBounds(100.0, 100.0, 110.0, 110.0),
            previous_bounds=ContactBounds(0.0, 0.0, 30.0, 30.0),
        )
        decision = adjust_young_track_bounds(
            lifecycle,
            current_age=3,
            current_class=3,
            candidate_bounds=candidate,
            neighbors=(neighbor,),
        )
        self.assertEqual(decision.adjusted_by_index, 0)
        self.assertEqual(decision.multiplier, 2)
        self.assertEqual(decision.bounds, ContactBounds(70.0, 10.0, 12.0, 82.0))

        touching = NeighborBoundsInput(
            **{**neighbor.__dict__, "previous_bounds": ContactBounds(10.0, 0.0, 30.0, 30.0)}
        )
        decision = adjust_young_track_bounds(
            lifecycle,
            current_age=3,
            current_class=3,
            candidate_bounds=candidate,
            neighbors=(touching,),
        )
        self.assertIsNone(decision.adjusted_by_index)

    def test_neighbor_bounds_obeys_current_class_age_limit(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        candidate = ContactBounds(10.0, 20.0, 12.0, 22.0)
        neighbor = NeighborBoundsInput(
            state=3,
            age=20,
            current_class=3,
            previous_class=0,
            current_bounds=ContactBounds(0.0, 0.0, 30.0, 30.0),
            previous_bounds=ContactBounds(0.0, 0.0, 30.0, 30.0),
        )
        decision = adjust_young_track_bounds(
            lifecycle,
            current_age=4,
            current_class=3,
            candidate_bounds=candidate,
            neighbors=(neighbor,),
        )
        self.assertEqual(decision.bounds, candidate)
        self.assertIsNone(decision.adjusted_by_index)

    def test_finger_policy_rejects_small_new_code_one_at_exact_boundary(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        decision = apply_finger_class_policy(
            lifecycle,
            FingerClassPolicyInput(
                age=2,
                old_class=4,
                proposed_class=1,
                score_gate_accepted=True,
                point_count=10,
                level_signal=10.0,
                local_context_active=False,
                counter_254=0,
                output_override=self._override(2, 4),
                special_pair_limit_active=True,
            ),
        )
        self.assertFalse(decision.transition_accepted)
        self.assertEqual(decision.code, 4)
        self.assertIn("new_code1_too_small", decision.reasons)

        accepted = apply_finger_class_policy(
            lifecycle,
            FingerClassPolicyInput(
                age=2,
                old_class=4,
                proposed_class=1,
                score_gate_accepted=True,
                point_count=11,
                level_signal=10.0,
                local_context_active=False,
                counter_254=0,
                output_override=self._override(2, 4),
                special_pair_limit_active=True,
            ),
        )
        self.assertTrue(accepted.transition_accepted)
        self.assertEqual(accepted.code, 1)

    def test_finger_policy_applies_level_context_and_final_demote_order(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        low_level = apply_finger_class_policy(
            lifecycle,
            FingerClassPolicyInput(
                age=99,
                old_class=4,
                proposed_class=3,
                score_gate_accepted=True,
                point_count=4,
                level_signal=7.49,
                local_context_active=False,
                counter_254=0,
                output_override=self._override(99, 4),
            ),
        )
        self.assertFalse(low_level.transition_accepted)
        self.assertIn("new_code3_level_age", low_level.reasons)

        context = apply_finger_class_policy(
            lifecycle,
            FingerClassPolicyInput(
                age=2,
                old_class=4,
                proposed_class=0,
                score_gate_accepted=True,
                point_count=1,
                level_signal=10.0,
                local_context_active=True,
                counter_254=2,
                output_override=self._override(2, 4),
            ),
        )
        self.assertFalse(context.transition_accepted)
        self.assertIn("new_code0_context_counter", context.reasons)

        demoted = apply_finger_class_policy(
            lifecycle,
            FingerClassPolicyInput(
                age=100,
                old_class=4,
                proposed_class=3,
                score_gate_accepted=True,
                point_count=4,
                level_signal=7.49,
                local_context_active=False,
                counter_254=0,
                output_override=self._override(100, 4),
                frame_level_exceeds_limit=True,
            ),
        )
        self.assertTrue(demoted.transition_accepted)
        self.assertEqual(demoted.code, 4)
        self.assertEqual(demoted.reasons, ("class3_demoted",))

        descriptor_demoted = apply_finger_class_policy(
            lifecycle,
            FingerClassPolicyInput(
                age=100,
                old_class=4,
                proposed_class=3,
                score_gate_accepted=True,
                point_count=4,
                level_signal=10.0,
                local_context_active=True,
                counter_254=0,
                output_override=self._override(100, 4),
            ),
        )
        self.assertEqual(descriptor_demoted.code, 4)

    def test_fallback_feature_profile_uses_exact_point_boundaries(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        self.assertFalse(
            uses_fallback_feature_profile(
                lifecycle, point_count=49, local_context_active=False
            )
        )
        self.assertTrue(
            uses_fallback_feature_profile(
                lifecycle, point_count=50, local_context_active=False
            )
        )
        self.assertFalse(
            uses_fallback_feature_profile(
                lifecycle, point_count=29, local_context_active=True
            )
        )
        self.assertTrue(
            uses_fallback_feature_profile(
                lifecycle, point_count=30, local_context_active=True
            )
        )
        with self.assertRaisesRegex(ValueError, "point count"):
            uses_fallback_feature_profile(
                lifecycle, point_count=-1, local_context_active=False
            )
        forced = apply_finger_class_policy(
            lifecycle,
            FingerClassPolicyInput(
                age=2,
                old_class=4,
                proposed_class=0,
                score_gate_accepted=True,
                point_count=20,
                level_signal=10.0,
                local_context_active=False,
                counter_254=3,
                output_override=self._override(2, 4),
                fallback_feature_profile=True,
            ),
        )
        self.assertEqual(forced.code, 1)
        self.assertIn("fallback_profile_code1", forced.reasons)

    def test_frame_level_limit_is_strict_and_unsigned(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        self.assertFalse(frame_level_exceeds_limit(lifecycle, (100, 300, 20)))
        self.assertTrue(frame_level_exceeds_limit(lifecycle, (100, 301, 20)))
        self.assertFalse(frame_level_exceeds_limit(lifecycle, ()))
        with self.assertRaisesRegex(ValueError, "unsigned short"):
            frame_level_exceeds_limit(lifecycle, (0x10000,))

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

        external_mode = apply_output_code_override(
            lifecycle,
            OutputOverrideInput(
                age=36,
                original_code=4,
                current_scores=(0.0, 0.0, 0.0, 0.0),
                previous_scores_newest_first=((0.0, 0.0, 0.0, 0.0),),
                counter_250=10,
                touches_sensor_edge=True,
                external_mode=True,
                external_predicate=True,
            ),
        )
        # Its special delay requires project force age > 49; 0x0c83 uses 35.
        self.assertEqual(external_mode.code, 1)
        self.assertEqual(external_mode.triggered, ("age_counter_code1",))

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

    def test_local_context_preserves_windows_source_region_order(self):
        lifecycle = ProjectLifecycle.from_dll(make_lifecycle_dll(), 0x0C83)
        base = dict(
            global_context_active=True,
            object_present=True,
            region_parameter_valid=True,
            immediate_source_active=False,
            previous_special_track_count=0,
            previous_track_region_contains=False,
            descriptor_mode=False,
            object_y=100.0,
            descriptor_region_contains=False,
        )
        self.assertTrue(resolve_local_context(lifecycle, LocalContextInput(**base)))
        self.assertTrue(
            resolve_local_context(
                lifecycle,
                LocalContextInput(**{**base, "immediate_source_active": True}),
            )
        )
        self.assertFalse(
            resolve_local_context(
                lifecycle,
                LocalContextInput(
                    **{
                        **base,
                        "previous_special_track_count": 1,
                        "previous_track_region_contains": False,
                    }
                ),
            )
        )
        self.assertTrue(
            resolve_local_context(
                lifecycle,
                LocalContextInput(
                    **{
                        **base,
                        "descriptor_mode": True,
                        "object_y": 9.999,
                    }
                ),
            )
        )
        at_edge = resolve_local_context(
            lifecycle,
            LocalContextInput(
                **{
                    **base,
                    "descriptor_mode": True,
                    "object_y": 10.0,
                    "descriptor_region_contains": False,
                }
            ),
        )
        self.assertFalse(at_edge)

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
