# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import struct
import unittest

from tools.extract_windows_classifier import PROJECT_CONFIG_OFFSET
from tools.windows_output_policy import (
    OutputEligibilityInput,
    ProjectOutputPolicy,
    State4HistorySample,
    State4SuppressionInput,
    advance_unmatched_track,
    evaluate_output_eligibility,
    evaluate_state4_suppression,
)


def make_output_policy_dll(project_id: int = 0x0C83) -> bytes:
    blob_length = 0x2000
    blob = bytearray(blob_length)
    blob[0:4] = b"PSDB"
    struct.pack_into("<HH", blob, 4, 4, project_id)
    struct.pack_into("<I", blob, 0x18, blob_length)
    blob[PROJECT_CONFIG_OFFSET + 0xE61] = 2
    rule = bytes.fromhex("f4ffefff02000400190002040dfdfbfc0b1e0204")
    blob[PROJECT_CONFIG_OFFSET + 0xE30 : PROJECT_CONFIG_OFFSET + 0xE44] = rule
    blob[PROJECT_CONFIG_OFFSET + 0xE44 : PROJECT_CONFIG_OFFSET + 0xE58] = rule
    return bytes(blob)


class WindowsOutputPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ProjectOutputPolicy.from_dll(make_output_policy_dll(), 0x0C83)

    def test_extracts_byte_wrapped_release_step(self):
        self.assertEqual(self.policy.state2_release_step_source, 2)
        self.assertEqual(self.policy.state2_release_step, 1)
        wrapped = bytearray(make_output_policy_dll())
        wrapped[PROJECT_CONFIG_OFFSET + 0xE61] = 0
        policy = ProjectOutputPolicy.from_dll(bytes(wrapped), 0x0C83)
        self.assertEqual(policy.state2_release_step, 0xFF)
        rule = self.policy.ordinary_state4_rule
        self.assertEqual((rule.score2_threshold, rule.score0_threshold), (-12, -17))
        self.assertEqual(
            (rule.default_counter_threshold, rule.context_counter_threshold),
            (2, 4),
        )
        self.assertEqual(rule.counter_maximum, 25)
        self.assertEqual(rule.average_score1_maximum, -3)
        self.assertEqual(
            (rule.score2_score1_margin, rule.score0_score1_margin), (-5, -4)
        )
        self.assertEqual(
            (rule.fallback_score0_adjustment, rule.fallback_score2_adjustment),
            (11, 30),
        )
        self.assertEqual(rule.history_scalar_range_maximum, 2)
        self.assertEqual(rule.release_counter_maximum, 4)

    def test_state_one_normal_split_and_transition_paths(self):
        normal = evaluate_output_eligibility(
            self.policy, OutputEligibilityInput(state=1, class_code=0, age=1)
        )
        self.assertEqual((normal.kind, normal.records), ("normal", 1))
        self.assertTrue(normal.primary)

        split = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=1,
                class_code=3,
                age=2,
                class3_configured_subcontacts=4,
                class3_enabled_subcontacts=3,
            ),
        )
        self.assertEqual((split.kind, split.records), ("split_class3", 3))

        suppressed = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=1,
                class_code=1,
                age=5,
                transition_output_flag=True,
                transition_age_limit=5,
            ),
        )
        self.assertFalse(suppressed.path_taken)
        emitted = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=1,
                class_code=1,
                age=4,
                transition_output_flag=True,
                transition_age_limit=5,
            ),
        )
        self.assertEqual(emitted.kind, "transition")
        self.assertFalse(emitted.primary)

    def test_descriptor_mode_enables_state_one_transition_output(self):
        decision = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=1,
                class_code=5,
                age=500,
                descriptor_mode=True,
            ),
        )
        self.assertEqual(decision.kind, "transition")

    def test_state_two_low_score_cleanup_is_strict(self):
        cleanup = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=2,
                class_code=0,
                age=5,
                current_scores=(-200.01, 999.0, -201.0, -300.0),
                release_counter=4,
            ),
        )
        self.assertEqual(cleanup.new_state, 0)
        self.assertEqual(cleanup.records, 0)
        self.assertIn("three_low_scores_cleanup", cleanup.reasons)

        boundary = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=2,
                class_code=0,
                age=5,
                current_scores=(-200.0, 999.0, -201.0, -300.0),
                release_counter=4,
            ),
        )
        self.assertEqual(boundary.kind, "retained_release")

    def test_state_two_release_counter_order_and_short_track_step(self):
        short = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=2,
                class_code=2,
                age=5,
                output_frame_count=2,
                release_counter=4,
            ),
        )
        self.assertEqual(short.release_counter, 4)
        self.assertFalse(short.frame_special_count_increment)

        retained = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=2,
                class_code=2,
                age=5,
                output_frame_count=3,
                release_counter=4,
            ),
        )
        self.assertEqual(retained.release_counter, 3)
        self.assertEqual(retained.new_state, 2)
        self.assertTrue(retained.frame_special_count_increment)

        exhausted = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=2,
                class_code=2,
                age=5,
                output_frame_count=3,
                release_counter=2,
            ),
        )
        self.assertEqual(exhausted.release_counter, 0)
        self.assertEqual(exhausted.new_state, 1)
        self.assertEqual(exhausted.kind, "retained_release")

    def test_state_two_transition_release_precedes_low_score_cleanup(self):
        decision = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=2,
                class_code=1,
                age=4,
                transition_output_flag=True,
                transition_age_limit=5,
                current_scores=(-999.0, -999.0, -999.0, -999.0),
                release_counter=4,
            ),
        )
        self.assertEqual(decision.kind, "transition_release")
        self.assertEqual(decision.new_state, 0)
        self.assertEqual(decision.records, 1)

    def test_state_four_retention_decrements_before_region_checks(self):
        retained = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=4, class_code=4, age=10, release_counter=3
            ),
        )
        self.assertEqual(retained.kind, "state4_retained")
        self.assertEqual(retained.release_counter, 2)
        self.assertEqual((retained.counter_250, retained.counter_252), (1, 0))

        excluded = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=4,
                class_code=4,
                age=10,
                release_counter=3,
                state4_region_excluded=True,
            ),
        )
        self.assertEqual(excluded.new_state, 0)
        self.assertEqual(excluded.release_counter, 0)
        self.assertEqual(excluded.records, 0)

    def test_output_frame_and_class_counters_follow_path_taken(self):
        emitted = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=1,
                class_code=0,
                age=3,
                output_frame_count=7,
                counter_250=5,
                counter_252=9,
            ),
        )
        self.assertEqual(emitted.output_frame_count, 8)
        self.assertEqual((emitted.counter_250, emitted.counter_252), (0, 10))

        silent = evaluate_output_eligibility(
            self.policy,
            OutputEligibilityInput(
                state=1,
                class_code=4,
                age=3,
                output_frame_count=7,
                counter_250=5,
                counter_252=9,
            ),
        )
        self.assertEqual(silent.output_frame_count, 0)
        self.assertEqual((silent.counter_250, silent.counter_252), (6, 0))

    def test_unmatched_state_one_selects_state_four_or_closes(self):
        suppressed = advance_unmatched_track(
            state=1,
            matched_this_frame=False,
            release_counter=0,
            active_secondary_count=2,
            state4_suppression_accepted=True,
        )
        self.assertEqual(suppressed.state, 4)
        self.assertEqual(suppressed.active_secondary_count, 2)

        closed = advance_unmatched_track(
            state=1,
            matched_this_frame=False,
            release_counter=0,
            active_secondary_count=2,
        )
        self.assertEqual(closed.state, 3)
        self.assertEqual(closed.active_secondary_count, 1)

    def test_unmatched_state_two_or_four_waits_for_release_counter(self):
        waiting = advance_unmatched_track(
            state=2,
            matched_this_frame=False,
            release_counter=1,
            active_secondary_count=2,
        )
        self.assertEqual(waiting.state, 2)
        self.assertEqual(waiting.active_secondary_count, 2)

        state2_closed = advance_unmatched_track(
            state=2,
            matched_this_frame=False,
            release_counter=0,
            active_secondary_count=2,
        )
        self.assertEqual(state2_closed.state, 3)
        self.assertEqual(state2_closed.active_secondary_count, 1)

        state4_closed = advance_unmatched_track(
            state=4,
            matched_this_frame=False,
            release_counter=0,
            active_secondary_count=2,
        )
        self.assertEqual(state4_closed.state, 3)
        self.assertEqual(state4_closed.active_secondary_count, 2)

    def test_matched_or_free_track_is_unchanged(self):
        matched = advance_unmatched_track(
            state=1,
            matched_this_frame=True,
            release_counter=0,
            active_secondary_count=1,
            state4_suppression_accepted=True,
        )
        self.assertEqual((matched.state, matched.reason), (1, "unchanged"))
        free = advance_unmatched_track(
            state=0,
            matched_this_frame=False,
            release_counter=0,
            active_secondary_count=1,
        )
        self.assertEqual((free.state, free.reason), (0, "unchanged"))

    @staticmethod
    def _state4_sample(
        class_code: int = 4,
        *,
        scalar_a: float = 10.0,
        scalar_b: float = 20.0,
        score0: float = -5.0,
        score1: float = -10.0,
        score2: float = -6.0,
    ) -> State4HistorySample:
        return State4HistorySample(
            class_code, scalar_a, scalar_b, score0, score1, score2
        )

    def _state4_input(self, **changes) -> State4SuppressionInput:
        values = dict(
            age=4,
            continuation_predicate=True,
            output_frame_count=3,
            counter_254=4,
            local_context_active=False,
            profile_flag_97=False,
            track_flag_11=False,
            spatial_profile_passed=True,
            level_signal=1.4399999380111694,
            fallback_feature_profile=False,
            metric_54=4.0,
            accumulated_metric_50=0.0,
            local_region_excluded=False,
            history_newest_first=(self._state4_sample(),) * 4,
        )
        values.update(changes)
        return State4SuppressionInput(**values)

    def test_state4_suppression_accepts_exact_project_history(self):
        decision = evaluate_state4_suppression(
            self.policy, self._state4_input()
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.release_counter, 4)

        long_history = evaluate_state4_suppression(
            self.policy,
            self._state4_input(
                age=10,
                history_newest_first=(self._state4_sample(),) * 10,
            ),
        )
        self.assertEqual(long_history.release_counter, 4)

    def test_state4_suppression_class_history_and_range_are_strict(self):
        wrong_history = list((self._state4_sample(),) * 4)
        wrong_history[2] = self._state4_sample(0)
        decision = evaluate_state4_suppression(
            self.policy,
            self._state4_input(history_newest_first=tuple(wrong_history)),
        )
        self.assertEqual(decision.reason, "history_class")

        at_range = list((self._state4_sample(),) * 4)
        at_range[0] = self._state4_sample(scalar_a=12.0)
        accepted = evaluate_state4_suppression(
            self.policy,
            self._state4_input(history_newest_first=tuple(at_range)),
        )
        self.assertTrue(accepted.accepted)
        above_range = list(at_range)
        above_range[0] = self._state4_sample(scalar_a=12.001)
        rejected = evaluate_state4_suppression(
            self.policy,
            self._state4_input(history_newest_first=tuple(above_range)),
        )
        self.assertEqual(rejected.reason, "scalar_a_range")

    def test_state4_suppression_preserves_score_boundaries(self):
        both_low = self._state4_sample(score0=-17.01, score2=-12.01)
        decision = evaluate_state4_suppression(
            self.policy,
            self._state4_input(history_newest_first=(both_low,) * 4),
        )
        self.assertEqual(decision.reason, "both_primary_scores_low")

        equality = self._state4_sample(score0=-17.0, score1=-13.0, score2=-12.0)
        accepted = evaluate_state4_suppression(
            self.policy,
            self._state4_input(history_newest_first=(equality,) * 4),
        )
        self.assertTrue(accepted.accepted)

        score1_high = self._state4_sample(score0=0.0, score1=-2.99, score2=0.0)
        rejected = evaluate_state4_suppression(
            self.policy,
            self._state4_input(history_newest_first=(score1_high,) * 4),
        )
        self.assertEqual(rejected.reason, "average_score1")

    def test_state4_suppression_context_fallback_and_region_order(self):
        context_counter = evaluate_state4_suppression(
            self.policy,
            self._state4_input(
                counter_254=3,
                local_context_active=True,
                spatial_profile_passed=False,
            ),
        )
        self.assertEqual(context_counter.reason, "spatial_profile")

        fallback = evaluate_state4_suppression(
            self.policy,
            self._state4_input(
                fallback_feature_profile=True,
                history_newest_first=(
                    self._state4_sample(score0=0.0, score1=-10.0, score2=20.0),
                )
                * 4,
            ),
        )
        self.assertTrue(fallback.accepted)

        excluded = evaluate_state4_suppression(
            self.policy, self._state4_input(local_region_excluded=True)
        )
        self.assertEqual(excluded.reason, "local_region_excluded")
        special = evaluate_state4_suppression(
            self.policy,
            self._state4_input(
                ordinary_mode=False,
                level_signal=0.0,
                local_region_excluded=True,
            ),
        )
        self.assertTrue(special.accepted)

    def test_state4_suppression_preconditions_and_metric_boundary(self):
        self.assertEqual(
            evaluate_state4_suppression(
                self.policy, self._state4_input(output_frame_count=4)
            ).reason,
            "output_frame_count",
        )
        self.assertEqual(
            evaluate_state4_suppression(
                self.policy, self._state4_input(counter_254=26)
            ).reason,
            "counter_maximum",
        )
        self.assertEqual(
            evaluate_state4_suppression(
                self.policy, self._state4_input(metric_54=4.0001)
            ).reason,
            "metric_54",
        )
        threshold_scores = self._state4_sample(
            score0=-16.0, score1=-20.0, score2=-11.0
        )
        equality_total = 2.4000000953674316 * 4
        equality = evaluate_state4_suppression(
            self.policy,
            self._state4_input(
                accumulated_metric_50=equality_total,
                history_newest_first=(threshold_scores,) * 4,
            ),
        )
        self.assertTrue(equality.accepted)
        above = evaluate_state4_suppression(
            self.policy,
            self._state4_input(
                accumulated_metric_50=equality_total + 0.001,
                history_newest_first=(threshold_scores,) * 4,
            ),
        )
        self.assertEqual(above.reason, "both_primary_scores_low")


if __name__ == "__main__":
    unittest.main()
