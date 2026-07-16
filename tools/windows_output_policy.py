#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Bounded final-output eligibility recovered from TouchPenProcessor0C83.dll.

This module mirrors the track/class branches and counter mutations in
FUN_1800426d8.  It deliberately leaves record serialization to the separately
recovered FUN_180041b80 geometry path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

if __package__:
    from tools.extract_windows_classifier import PROJECT_CONFIG_OFFSET, find_project_blob
else:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.extract_windows_classifier import PROJECT_CONFIG_OFFSET, find_project_blob


STATE2_LOW_SCORE_LIMIT = -200.0
STATE4_SIGNAL_OFFSET = 0.6000000238418579
STATE4_SIGNAL_STEP = 0.002220354275777936
STATE4_SPATIAL_LEVEL_MINIMUM = 0.15000000596046448
STATE4_ACCUMULATED_METRIC_LIMIT = 2.4000000953674316
STATE4_MODE_LEVEL_MINIMUMS = (-0.0, 1.4399999380111694)


@dataclass(frozen=True)
class State4SuppressionRule:
    score2_threshold: int
    score0_threshold: int
    default_counter_threshold: int
    context_counter_threshold: int
    counter_maximum: int
    average_score1_maximum: int
    score2_score1_margin: int
    score0_score1_margin: int
    fallback_score0_adjustment: int
    fallback_score2_adjustment: int
    history_scalar_range_maximum: int
    release_counter_maximum: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> "State4SuppressionRule":
        if offset < 0 or offset + 0x14 > len(data):
            raise ValueError("state-four suppression record is outside the PSDB")
        score2, score0, default_count, context_count, counter_max = (
            struct.unpack_from("<5h", data, offset)
        )
        return cls(
            score2,
            score0,
            default_count,
            context_count,
            counter_max,
            struct.unpack_from("<b", data, offset + 0x0D)[0],
            struct.unpack_from("<b", data, offset + 0x0E)[0],
            struct.unpack_from("<b", data, offset + 0x0F)[0],
            struct.unpack_from("<b", data, offset + 0x10)[0],
            struct.unpack_from("<b", data, offset + 0x11)[0],
            data[offset + 0x12],
            data[offset + 0x13],
        )


@dataclass(frozen=True)
class ProjectOutputPolicy:
    project_id: int
    state2_release_step_source: int
    state4_signal_baseline: float
    special_state4_rule: State4SuppressionRule
    ordinary_state4_rule: State4SuppressionRule

    @classmethod
    def from_dll(cls, data: bytes, project_id: int) -> "ProjectOutputPolicy":
        blob_offset, blob_length = find_project_blob(data, project_id)
        required = PROJECT_CONFIG_OFFSET + 0xE62
        if required > blob_length:
            raise ValueError("PSDB is too short for final-output policy")
        config = blob_offset + PROJECT_CONFIG_OFFSET
        return cls(
            project_id,
            data[config + 0xE61],
            struct.unpack_from("<f", data, config + 0x0C)[0],
            State4SuppressionRule.from_bytes(data, config + 0xE30),
            State4SuppressionRule.from_bytes(data, config + 0xE44),
        )

    @property
    def state2_release_step(self) -> int:
        """Return the DLL's byte-wrapped `(project[e61] - 1)` value."""
        return (self.state2_release_step_source - 1) & 0xFF

    @property
    def state4_signal_threshold(self) -> int:
        """Return FUN_1800426d8's float32-derived neighborhood byte floor."""
        value = _float32(1.0 - self.state4_signal_baseline)
        value = _float32(value - STATE4_SIGNAL_OFFSET)
        value = _float32(value / STATE4_SIGNAL_STEP)
        return int(_float32(value + 0.5)) & 0xFF


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def state4_neighborhood_all_above(
    policy: ProjectOutputPolicy,
    grid: tuple[tuple[int, ...], ...],
    *,
    x: float,
    y: float,
) -> bool:
    """Mirror the bounded 3x3 raw-grid predicate in FUN_1800426d8."""
    if not grid or not grid[0]:
        raise ValueError("grid must not be empty")
    width = len(grid[0])
    if any(len(row) != width for row in grid):
        raise ValueError("grid rows must have equal width")
    if any(not 0 <= value <= 0xFF for row in grid for value in row):
        raise ValueError("grid values must fit an unsigned byte")
    center_x = int(x + 0.5) & 0xFF
    center_y = int(y + 0.5) & 0xFF
    threshold = policy.state4_signal_threshold
    for row in range(center_y - 1, center_y + 2):
        if not 0 <= row < len(grid):
            continue
        for column in range(center_x - 1, center_x + 2):
            if 0 <= column < width and grid[row][column] < threshold:
                return False
    return True


@dataclass(frozen=True)
class OutputEligibilityInput:
    state: int
    class_code: int
    age: int
    descriptor_mode: bool = False
    transition_output_flag: bool = False
    transition_age_limit: int = 0
    class3_configured_subcontacts: int = 0
    class3_enabled_subcontacts: int = 0
    current_scores: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    output_frame_count: int = 0
    release_counter: int = 0
    counter_250: int = 0
    counter_252: int = 0
    state4_neighborhood_all_above: bool = True
    state4_region_excluded: bool = False


@dataclass(frozen=True)
class OutputEligibilityDecision:
    kind: str
    records: int
    path_taken: bool
    primary: bool
    new_state: int
    release_counter: int
    output_frame_count: int
    counter_250: int
    counter_252: int
    frame_special_count_increment: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class UnmatchedLifecycleDecision:
    state: int
    active_secondary_count: int
    state4_suppression_accepted: bool
    reason: str


@dataclass(frozen=True)
class State4HistorySample:
    class_code: int
    scalar_a: float
    scalar_b: float
    score0: float
    score1: float
    score2: float


@dataclass(frozen=True)
class State4SuppressionInput:
    age: int
    continuation_predicate: bool
    output_frame_count: int
    counter_254: int
    local_context_active: bool
    profile_flag_97: bool
    track_flag_11: bool
    spatial_profile_passed: bool
    level_signal: float
    fallback_feature_profile: bool
    metric_54: float
    accumulated_metric_50: float
    local_region_excluded: bool
    history_newest_first: tuple[State4HistorySample, ...]
    ordinary_mode: bool = True


@dataclass(frozen=True)
class State4SuppressionDecision:
    accepted: bool
    release_counter: int
    reason: str


def evaluate_state4_suppression(
    policy: ProjectOutputPolicy, inputs: State4SuppressionInput
) -> State4SuppressionDecision:
    """Mirror FUN_18003fbb8's state-four shape/history predicate."""
    if inputs.age <= 0:
        raise ValueError("track age must be positive")
    if not 0 <= inputs.output_frame_count <= 0xFFFF:
        raise ValueError("output frame count must fit an unsigned short")
    if not 0 <= inputs.counter_254 <= 0xFFFF:
        raise ValueError("counter 254 must fit an unsigned short")
    if not inputs.continuation_predicate:
        return State4SuppressionDecision(False, 0, "continuation_failed")
    if inputs.output_frame_count > 3:
        return State4SuppressionDecision(False, 0, "output_frame_count")

    rule = (
        policy.ordinary_state4_rule
        if inputs.ordinary_mode
        else policy.special_state4_rule
    )
    required = min(inputs.age, 10)
    if len(inputs.history_newest_first) < required:
        raise ValueError(f"state-four predicate requires {required} history samples")
    samples = inputs.history_newest_first[:required]
    current_class = samples[0].class_code
    if current_class != 4:
        allowed = (0, 2) if inputs.ordinary_mode else (0, 1, 2)
        if current_class not in allowed or required < 2 or samples[1].class_code != 4:
            return State4SuppressionDecision(False, 0, "current_previous_class")
    if inputs.counter_254 > rule.counter_maximum:
        return State4SuppressionDecision(False, 0, "counter_maximum")

    selected_counter = (
        rule.context_counter_threshold
        if inputs.local_context_active
        else rule.default_counter_threshold
    )
    if (
        not inputs.profile_flag_97
        and (inputs.counter_254 < selected_counter or inputs.track_flag_11)
        and (
            not inputs.spatial_profile_passed
            or inputs.level_signal < STATE4_SPATIAL_LEVEL_MINIMUM
        )
    ):
        return State4SuppressionDecision(False, 0, "spatial_profile")
    if inputs.metric_54 > 4.0:
        return State4SuppressionDecision(False, 0, "metric_54")
    mode_index = 1 if inputs.ordinary_mode else 0
    if (
        not inputs.profile_flag_97
        and inputs.level_signal < STATE4_MODE_LEVEL_MINIMUMS[mode_index]
    ):
        return State4SuppressionDecision(False, 0, "mode_level")

    for index, sample in enumerate(samples):
        if not 0 <= sample.class_code <= 5:
            raise ValueError("history class code must be in [0, 5]")
        if index and sample.class_code != 4 and (
            inputs.ordinary_mode or sample.class_code != 1
        ):
            return State4SuppressionDecision(False, 0, "history_class")

    scalar_a_values = [sample.scalar_a for sample in samples]
    scalar_b_values = [sample.scalar_b for sample in samples]
    if rule.history_scalar_range_maximum < (
        max(scalar_a_values) - min(scalar_a_values)
    ):
        return State4SuppressionDecision(False, 0, "scalar_a_range")
    if rule.history_scalar_range_maximum < (
        max(scalar_b_values) - min(scalar_b_values)
    ):
        return State4SuppressionDecision(False, 0, "scalar_b_range")

    divisor = float(required)
    average0 = sum(sample.score0 for sample in samples) / divisor
    average1 = sum(sample.score1 for sample in samples) / divisor
    average2 = sum(sample.score2 for sample in samples) / divisor
    score0_adjustment = 0
    score2_adjustment = 0
    if inputs.fallback_feature_profile:
        score0_adjustment = rule.fallback_score0_adjustment
        score2_adjustment = rule.fallback_score2_adjustment
    if (
        STATE4_ACCUMULATED_METRIC_LIMIT
        < inputs.accumulated_metric_50 / inputs.age
    ):
        score0_adjustment += 3
        score2_adjustment += 3

    score0_below = average0 < rule.score0_threshold + score0_adjustment
    score2_below = average2 < rule.score2_threshold + score2_adjustment
    if score0_below and score2_below:
        return State4SuppressionDecision(False, 0, "both_primary_scores_low")
    if rule.average_score1_maximum < average1:
        return State4SuppressionDecision(False, 0, "average_score1")

    if score0_below:
        margin_passed = rule.score2_score1_margin <= average2 - average1
    else:
        margin_passed = rule.score0_score1_margin <= average0 - average1
        if not score2_below and not margin_passed:
            margin_passed = rule.score2_score1_margin <= average2 - average1
    if not margin_passed:
        return State4SuppressionDecision(False, 0, "score_margin")
    if inputs.ordinary_mode and inputs.local_region_excluded:
        return State4SuppressionDecision(False, 0, "local_region_excluded")

    return State4SuppressionDecision(
        True, min(required, rule.release_counter_maximum), "accepted"
    )


def advance_unmatched_track(
    *,
    state: int,
    matched_this_frame: bool,
    release_counter: int,
    active_secondary_count: int,
    state4_suppression_accepted: bool = False,
) -> UnmatchedLifecycleDecision:
    """Mirror FUN_180043b10's state mutations for one track.

    ``state4_suppression_accepted`` is the result of FUN_18003fbb8's shape and
    history predicate. FUN_18003ed78 is telemetry/history bookkeeping and does
    not mutate the track state.
    """
    if not 0 <= state <= 4:
        raise ValueError("track state must be in [0, 4]")
    if not 0 <= release_counter <= 0xFF:
        raise ValueError("release counter must fit an unsigned byte")
    if not 0 <= active_secondary_count <= 0xFF:
        raise ValueError("active-secondary count must fit an unsigned byte")
    if state == 0 or matched_this_frame:
        return UnmatchedLifecycleDecision(
            state, active_secondary_count, False, "unchanged"
        )

    if state == 1:
        if state4_suppression_accepted:
            return UnmatchedLifecycleDecision(
                4, active_secondary_count, True, "state1_to_state4"
            )
        if active_secondary_count:
            active_secondary_count -= 1
        return UnmatchedLifecycleDecision(
            3, active_secondary_count, False, "state1_to_state3"
        )

    if state in (2, 4) and release_counter == 0:
        if state == 2 and active_secondary_count:
            active_secondary_count -= 1
        return UnmatchedLifecycleDecision(
            3, active_secondary_count, False, f"state{state}_to_state3"
        )

    return UnmatchedLifecycleDecision(
        state, active_secondary_count, False, "release_counter_active"
    )


def evaluate_output_eligibility(
    policy: ProjectOutputPolicy, inputs: OutputEligibilityInput
) -> OutputEligibilityDecision:
    """Mirror FUN_1800426d8 for one track before record serialization."""
    if not 0 <= inputs.state <= 4:
        raise ValueError("track state must be in [0, 4]")
    if not 0 <= inputs.class_code <= 5:
        raise ValueError("class code must be in [0, 5]")
    if inputs.age < 0 or inputs.transition_age_limit < 0:
        raise ValueError("ages must not be negative")
    for name, value in (
        ("output frame count", inputs.output_frame_count),
        ("counter 250", inputs.counter_250),
        ("counter 252", inputs.counter_252),
    ):
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"{name} must fit an unsigned short")
    if not 0 <= inputs.release_counter <= 0xFF:
        raise ValueError("release counter must fit an unsigned byte")
    if not 0 <= inputs.class3_configured_subcontacts <= 0xFF:
        raise ValueError("configured class-three count must fit an unsigned byte")
    if not 0 <= inputs.class3_enabled_subcontacts <= min(
        inputs.class3_configured_subcontacts, 9
    ):
        raise ValueError("enabled class-three subcontacts exceed configured count")

    state = inputs.state
    release_counter = inputs.release_counter
    kind = "none"
    records = 0
    path_taken = False
    primary = False
    frame_special = False
    reasons: list[str] = []

    if state == 1:
        if inputs.class_code in (0, 2):
            kind = "normal"
            records = 1
            path_taken = True
            primary = True
        elif inputs.class_code == 3:
            path_taken = True
            primary = True
            if inputs.class3_configured_subcontacts < 2:
                kind = "normal_class3"
                records = 1
            else:
                kind = "split_class3"
                records = inputs.class3_enabled_subcontacts
        elif inputs.class_code in (1, 5) and (
            inputs.descriptor_mode
            or (
                inputs.transition_output_flag
                and inputs.age < inputs.transition_age_limit
            )
        ):
            kind = "transition"
            records = 1
            path_taken = True
            reasons.append("class1_or_5_transition")

    elif state == 2:
        if (
            not inputs.descriptor_mode
            and inputs.transition_output_flag
            and inputs.age < inputs.transition_age_limit
        ):
            kind = "transition_release"
            records = 1
            path_taken = True
            state = 0
            release_counter = 0
            reasons.append("transition_release")
        elif all(
            inputs.current_scores[index] < STATE2_LOW_SCORE_LIMIT
            for index in (0, 2, 3)
        ):
            state = 0
            release_counter = 0
            reasons.append("three_low_scores_cleanup")
        elif inputs.class_code in (0, 2, 3):
            step = policy.state2_release_step
            if inputs.output_frame_count < 3:
                step = 0
            else:
                frame_special = True
            if step < release_counter - 1:
                release_counter = (release_counter - step) & 0xFF
            else:
                release_counter = 0
                state = 1
                reasons.append("release_counter_exhausted")
            kind = "retained_release"
            records = 1
            path_taken = True
            primary = True
        else:
            state = 1
            release_counter = 0
            reasons.append("non_retained_class")

    elif state == 4:
        if release_counter:
            release_counter -= 1
        if not inputs.state4_neighborhood_all_above:
            state = 0
            release_counter = 0
            reasons.append("state4_neighborhood_failed")
        elif inputs.state4_region_excluded:
            state = 0
            release_counter = 0
            reasons.append("state4_region_excluded")
        else:
            kind = "state4_retained"
            records = 1
            path_taken = True
            primary = True

    output_frame_count = (
        (inputs.output_frame_count + 1) & 0xFFFF if path_taken else 0
    )
    if inputs.class_code == 4:
        counter_250 = (inputs.counter_250 + 1) & 0xFFFF
        counter_252 = 0
    else:
        counter_250 = 0
        counter_252 = (inputs.counter_252 + 1) & 0xFFFF

    return OutputEligibilityDecision(
        kind,
        records,
        path_taken,
        primary,
        state,
        release_counter,
        output_frame_count,
        counter_250,
        counter_252,
        frame_special,
        tuple(reasons),
    )
