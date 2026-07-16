#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Extract and evaluate the project-0x0c83 class-transition policy.

The layout and predicates mirror TouchPenProcessor0C83.dll functions
FUN_180045038 (current-frame score gate) and FUN_180044db0 (history gate).
Callers must supply the context-dependent score adjustments selected by the
surrounding Windows policy; this module does not guess those branches.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import struct
from typing import Iterable, Sequence

if __package__:
    from tools.extract_windows_classifier import PROJECT_CONFIG_OFFSET, find_project_blob
else:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.extract_windows_classifier import PROJECT_CONFIG_OFFSET, find_project_blob


CLASS_COUNT = 4
UNCLASSIFIED = CLASS_COUNT
OLD_CLASS_COUNT = CLASS_COUNT + 1
TRANSITION_COUNT = OLD_CLASS_COUNT * CLASS_COUNT
HISTORY_CAPACITY = 10

# FUN_180045038/FUN_180044db0 first form a pointer at project config +0x8d8,
# then address fields beginning at +0x24. Express the actual record boundary so
# every extracted field fits inside the 0x30-byte stride.
TRANSITION_TABLE_OFFSET = 0x8FC
TRANSITION_STRIDE = 0x30

HISTORY_MARGIN_OFFSET = 0x04
CURRENT_MARGIN_OFFSET = 0x18
ABSOLUTE_MIN_OFFSET = 0x28
CONTEXT_SCORE_BIAS_OFFSET = 0x2A
HISTORY_DEPTH_OFFSET = 0x2B
INITIAL_AGE_LIMIT_OFFSET = 0x2C
CONTEXT_ALLOWED_OFFSET = 0x2D
CONTEXT_EXTRA_HISTORY_OFFSET = 0x2E

# FUN_180049880 direct DLL literals.
OVERRIDE_DISABLED_SCORE = -9999.0
OVERRIDE_AVERAGE_METRIC_LIMIT = 2.4000000953674316
OVERRIDE_LEVEL_SIGNAL_MINIMUM = 0.11999999731779099
OVERRIDE_LOW_SCORE_LIMIT = -100.0

# Direct float literals at 0x180041a28..0x180041a34.  Names stay structural
# because the guarded runtime mode is outside the ordinary finger path.
SPECIAL_TRACK_METRIC_MINIMUM = 0.15000000596046448
EXTERNAL_NEW_TRACK_HISTORY_SPREAD_LIMIT = 0.6000000238418579
EXTERNAL_DISABLED_CANDIDATE_METRIC = -9999.0
EXTERNAL_EXISTING_TRACK_HISTORY_SPREAD_LIMIT = 0.30000001192092896

# Direct non-project limits in FUN_180041150.  The four-point limit is the
# ordinary project-0x0c83 path; ten is selected only by the separately gated
# single-pair mode.  Fourteen applies to an established class-zero track.
NEW_CONTACT_CODE1_POINT_LIMIT = 4
SINGLE_PAIR_CODE1_POINT_LIMIT = 10
ESTABLISHED_CODE1_POINT_MINIMUM = 14


def _class_index(value: int) -> int:
    if not 0 <= value < CLASS_COUNT:
        raise ValueError(f"class must be in [0, {CLASS_COUNT - 1}], got {value}")
    return value


def _old_class_index(value: int) -> int:
    if not 0 <= value < OLD_CLASS_COUNT:
        raise ValueError(
            f"old class must be in [0, {OLD_CLASS_COUNT - 1}], got {value}"
        )
    return value


def _scores(values: Sequence[float]) -> tuple[float, ...]:
    if len(values) != CLASS_COUNT:
        raise ValueError(f"expected {CLASS_COUNT} scores, got {len(values)}")
    return tuple(float(value) for value in values)


@dataclass(frozen=True)
class TransitionRule:
    old_class: int
    new_class: int
    history_score_margins: tuple[int, int, int, int]
    current_score_margins: tuple[int, int, int, int]
    absolute_score_min: int
    context_score_bias: int
    history_depth: int
    initial_age_limit: int
    context_allowed: bool
    context_extra_history: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, old_class: int, new_class: int
    ) -> "TransitionRule":
        if offset < 0 or offset + TRANSITION_STRIDE > len(data):
            raise ValueError("transition record is outside the PSDB blob")
        history_count = struct.unpack_from("<I", data, offset)[0]
        current_count = struct.unpack_from("<I", data, offset + 0x14)[0]
        if history_count != CLASS_COUNT or current_count != CLASS_COUNT:
            raise ValueError(
                "transition record has an unsupported score-vector length"
            )
        return cls(
            old_class=_old_class_index(old_class),
            new_class=_class_index(new_class),
            history_score_margins=struct.unpack_from(
                "<4i", data, offset + HISTORY_MARGIN_OFFSET
            ),
            current_score_margins=struct.unpack_from(
                "<4i", data, offset + CURRENT_MARGIN_OFFSET
            ),
            absolute_score_min=struct.unpack_from(
                "<h", data, offset + ABSOLUTE_MIN_OFFSET
            )[0],
            context_score_bias=struct.unpack_from(
                "<b", data, offset + CONTEXT_SCORE_BIAS_OFFSET
            )[0],
            history_depth=data[offset + HISTORY_DEPTH_OFFSET],
            initial_age_limit=data[offset + INITIAL_AGE_LIMIT_OFFSET],
            context_allowed=bool(data[offset + CONTEXT_ALLOWED_OFFSET]),
            context_extra_history=data[offset + CONTEXT_EXTRA_HISTORY_OFFSET],
        )

    def required_history(self, *, extra_context: bool = False) -> int:
        """Return FUN_180044db0's selected history length."""
        return self.history_depth + (
            self.context_extra_history if extra_context else 0
        )

    def passes_current_scores(
        self,
        scores: Sequence[float],
        *,
        context_bias: float = 0.0,
        comparison_bias: float = 0.0,
        absolute_min_override: float | None = None,
        track_context: bool = False,
    ) -> bool:
        """Mirror FUN_180045038's four-score comparisons.

        ``context_bias`` is the fVar9 adjustment and affects the pairwise and
        absolute comparisons. ``comparison_bias`` is fVar10 and affects only
        pairwise margins. The Windows special branch can also replace the
        absolute floor, hence ``absolute_min_override``.
        """
        values = _scores(scores)
        if self.old_class == self.new_class:
            return True
        if track_context and not self.context_allowed:
            return False
        selected = values[self.new_class]
        for other_class, margin in enumerate(self.current_score_margins):
            if other_class == self.new_class:
                continue
            if selected - values[other_class] < (
                margin + context_bias + comparison_bias
            ):
                return False
        absolute_min = (
            self.absolute_score_min
            if absolute_min_override is None
            else absolute_min_override
        )
        return selected >= absolute_min + context_bias

    def passes_score_history(
        self,
        history: Iterable[Sequence[float]],
        *,
        context_bias: float = 0.0,
        comparison_bias: float = 0.0,
        extra_context: bool = False,
    ) -> bool:
        """Mirror FUN_180044db0 for newest-first score history."""
        if self.old_class == self.new_class:
            return True
        required = self.required_history(extra_context=extra_context)
        if required > HISTORY_CAPACITY:
            return False
        samples = tuple(_scores(sample) for sample in history)
        if len(samples) < required:
            return False
        for values in samples[:required]:
            selected = values[self.new_class]
            for other_class, margin in enumerate(self.history_score_margins):
                if other_class == self.new_class:
                    continue
                if selected - values[other_class] < (
                    margin + context_bias + comparison_bias
                ):
                    return False
            if selected < self.absolute_score_min + context_bias:
                return False
        return True

    def summary(self) -> dict[str, object]:
        return {
            "old_class": self.old_class,
            "new_class": self.new_class,
            "history_score_margins": self.history_score_margins,
            "current_score_margins": self.current_score_margins,
            "absolute_score_min": self.absolute_score_min,
            "context_score_bias": self.context_score_bias,
            "history_depth": self.history_depth,
            "initial_age_limit": self.initial_age_limit,
            "context_allowed": self.context_allowed,
            "context_extra_history": self.context_extra_history,
        }


@dataclass(frozen=True)
class NeighborBoundsRule:
    """One class record consumed by FUN_180049dd0.

    The four signed values are deliberately named by the bounds they modify.
    They are not coordinate-filter coefficients: the helper subtracts them
    from a young track's current classification window only when another
    active track strictly encloses the candidate component.
    """

    min_x_adjustment: int
    min_y_adjustment: int
    max_x_adjustment: int
    max_y_adjustment: int
    enabled: bool
    current_age_maximum: int
    enclosing_age_double_after: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> "NeighborBoundsRule":
        if offset < 0 or offset + 0x0F > len(data):
            raise ValueError("neighbor-bounds record is outside the PSDB blob")
        adjustments = struct.unpack_from("<4h", data, offset)
        return cls(
            *adjustments,
            bool(data[offset + 0x08]),
            data[offset + 0x09],
            data[offset + 0x0A],
        )


@dataclass(frozen=True)
class ProjectLifecycle:
    project_id: int
    psdb_offset: int
    psdb_length: int
    special_single_pair_matching: bool
    normal_match_radius: float
    single_pair_match_radius: float
    class_point_count_minimums: tuple[int, int, int, int]
    class_point_count_maximums: tuple[int, int, int, int]
    context_window_frames: int
    frame_level_limit: int
    context_source_resets_window: bool
    context_regions_enabled: bool
    context_region_distance: int
    output_merge_squared_limit: float
    output_merge_disabled_limit: float
    override_score2_floor_without_pen: float
    override_score2_floor_with_pen: float
    override_pen_distance_squared: float
    override_context_age_adjustment: int
    override_age_minimum: int
    override_age_maximum: int
    override_force_age: int
    override_force_counter: int
    override_candidate_margin: int
    override_default_margin: int
    override_context_margin: int
    override_pen_margin: int
    override_minimum_counter: int
    override_score3_floor: int
    unclassified_code3_level_threshold: float
    unclassified_code3_age_release: int
    pen_force_age_maximum: int
    pen_force_distance_squared: int
    pen_force_enabled: bool
    normal_feature_point_limit: int
    context_feature_point_limit: int
    neighbor_bounds_rules: tuple[NeighborBoundsRule, ...]
    rules: tuple[TransitionRule, ...]

    @classmethod
    def from_dll(cls, data: bytes, project_id: int) -> "ProjectLifecycle":
        blob_offset, blob_length = find_project_blob(data, project_id)
        table_in_blob = PROJECT_CONFIG_OFFSET + TRANSITION_TABLE_OFFSET
        required = max(
            table_in_blob + TRANSITION_COUNT * TRANSITION_STRIDE,
            PROJECT_CONFIG_OFFSET + 0xE9B,
            0xB9C,
        )
        if required > blob_length:
            raise ValueError("PSDB is too short for the transition table")
        table = blob_offset + table_in_blob
        rules = []
        for old_class in range(OLD_CLASS_COUNT):
            for new_class in range(CLASS_COUNT):
                index = new_class + old_class * CLASS_COUNT
                rules.append(
                    TransitionRule.from_bytes(
                        data,
                        table + index * TRANSITION_STRIDE,
                        old_class,
                        new_class,
                    )
                )
        config = blob_offset + PROJECT_CONFIG_OFFSET
        neighbor_bounds = tuple(
            NeighborBoundsRule.from_bytes(data, config + 0xD84 + index * 0x10)
            for index in range(CLASS_COUNT)
        )
        return cls(
            project_id,
            blob_offset,
            blob_length,
            bool(data[config + 0x8D8]),
            struct.unpack_from("<f", data, config + 0x8DC)[0],
            struct.unpack_from("<f", data, config + 0x8E0)[0],
            struct.unpack_from("<4H", data, config + 0xDE4),
            struct.unpack_from("<4H", data, config + 0xDF4),
            struct.unpack_from("<H", data, config + 0xE7A)[0],
            struct.unpack_from("<H", data, config + 0xE78)[0],
            bool(data[config + 0xE98]),
            bool(data[config + 0xE99]),
            data[config + 0xE9A],
            struct.unpack_from("<f", data, blob_offset + 0xB90)[0],
            struct.unpack_from("<f", data, blob_offset + 0xB98)[0],
            struct.unpack_from("<f", data, config + 0xE00)[0],
            struct.unpack_from("<f", data, config + 0xE04)[0],
            struct.unpack_from("<f", data, config + 0xE08)[0],
            struct.unpack_from("<b", data, config + 0xE0C)[0],
            data[config + 0xE0D],
            data[config + 0xE0E],
            data[config + 0xE0F],
            data[config + 0xE10],
            struct.unpack_from("<b", data, config + 0xE11)[0],
            struct.unpack_from("<b", data, config + 0xE12)[0],
            struct.unpack_from("<b", data, config + 0xE13)[0],
            struct.unpack_from("<b", data, config + 0xE14)[0],
            data[config + 0xE15],
            struct.unpack_from("<h", data, config + 0xCB4)[0],
            struct.unpack_from("<f", data, config + 0x8E8)[0],
            struct.unpack_from("<H", data, config + 0x8EC)[0],
            struct.unpack_from("<H", data, config + 0xE66)[0],
            struct.unpack_from("<H", data, config + 0xE68)[0],
            bool(data[config + 0xE6A]),
            struct.unpack_from("<H", data, config + 0xE80)[0],
            struct.unpack_from("<H", data, config + 0xE82)[0],
            neighbor_bounds,
            tuple(rules),
        )

    def rule(self, old_class: int, new_class: int) -> TransitionRule:
        old_class = _old_class_index(old_class)
        new_class = _class_index(new_class)
        return self.rules[new_class + old_class * CLASS_COUNT]

    def summary(self) -> dict[str, object]:
        return {
            "project_id": f"0x{self.project_id:04x}",
            "psdb_offset": self.psdb_offset,
            "psdb_length": self.psdb_length,
            "special_single_pair_matching": self.special_single_pair_matching,
            "normal_match_radius": self.normal_match_radius,
            "single_pair_match_radius": self.single_pair_match_radius,
            "class_point_count_minimums": self.class_point_count_minimums,
            "class_point_count_maximums": self.class_point_count_maximums,
            "context_window_frames": self.context_window_frames,
            "frame_level_limit": self.frame_level_limit,
            "context_source_resets_window": self.context_source_resets_window,
            "context_regions_enabled": self.context_regions_enabled,
            "context_region_distance": self.context_region_distance,
            "output_merge_squared_limit": self.output_merge_squared_limit,
            "output_merge_disabled_limit": self.output_merge_disabled_limit,
            "override_score2_floor_without_pen": self.override_score2_floor_without_pen,
            "override_score2_floor_with_pen": self.override_score2_floor_with_pen,
            "override_pen_distance_squared": self.override_pen_distance_squared,
            "override_context_age_adjustment": self.override_context_age_adjustment,
            "override_age_minimum": self.override_age_minimum,
            "override_age_maximum": self.override_age_maximum,
            "override_force_age": self.override_force_age,
            "override_force_counter": self.override_force_counter,
            "override_candidate_margin": self.override_candidate_margin,
            "override_default_margin": self.override_default_margin,
            "override_context_margin": self.override_context_margin,
            "override_pen_margin": self.override_pen_margin,
            "override_minimum_counter": self.override_minimum_counter,
            "override_score3_floor": self.override_score3_floor,
            "unclassified_code3_level_threshold": self.unclassified_code3_level_threshold,
            "unclassified_code3_age_release": self.unclassified_code3_age_release,
            "pen_force_age_maximum": self.pen_force_age_maximum,
            "pen_force_distance_squared": self.pen_force_distance_squared,
            "pen_force_enabled": self.pen_force_enabled,
            "normal_feature_point_limit": self.normal_feature_point_limit,
            "context_feature_point_limit": self.context_feature_point_limit,
            "neighbor_bounds_rules": [
                rule.__dict__ for rule in self.neighbor_bounds_rules
            ],
            "rules": [rule.summary() for rule in self.rules],
        }


@dataclass(frozen=True)
class ContactBounds:
    min_x: float
    min_y: float
    max_x: float
    max_y: float


@dataclass(frozen=True)
class NeighborBoundsInput:
    """Only the neighboring-track fields read by FUN_180049dd0."""

    state: int
    age: int
    current_class: int
    previous_class: int
    current_bounds: ContactBounds
    previous_bounds: ContactBounds


@dataclass(frozen=True)
class NeighborBoundsDecision:
    bounds: ContactBounds
    adjusted_by_index: int | None
    multiplier: int


def adjust_young_track_bounds(
    lifecycle: ProjectLifecycle,
    *,
    current_age: int,
    current_class: int,
    candidate_bounds: ContactBounds,
    neighbors: Sequence[NeighborBoundsInput],
) -> NeighborBoundsDecision:
    """Mirror FUN_180049dd0's first-enclosing-neighbor adjustment."""
    if current_age < 0:
        raise ValueError("track age must be non-negative")
    current_class = _class_index(current_class)
    if (
        candidate_bounds.min_x > candidate_bounds.max_x
        or candidate_bounds.min_y > candidate_bounds.max_y
    ):
        raise ValueError("candidate bounds are inverted")

    current_rule = lifecycle.neighbor_bounds_rules[current_class]
    if current_age > current_rule.current_age_maximum:
        return NeighborBoundsDecision(candidate_bounds, None, 0)

    for index, neighbor in enumerate(neighbors):
        if neighbor.age < 0:
            raise ValueError("neighbor age must be non-negative")
        if neighbor.state == 0:
            continue
        if neighbor.state != 3 and neighbor.age <= 1:
            continue
        selected_class = (
            neighbor.current_class if neighbor.state == 3 else neighbor.previous_class
        )
        selected_class = _class_index(selected_class)
        selected_bounds = (
            neighbor.current_bounds if neighbor.state == 3 else neighbor.previous_bounds
        )
        rule = lifecycle.neighbor_bounds_rules[selected_class]
        if not rule.enabled:
            continue
        if not (
            selected_bounds.min_x < candidate_bounds.min_x
            and candidate_bounds.max_x < selected_bounds.max_x
            and selected_bounds.min_y < candidate_bounds.min_y
            and candidate_bounds.max_y < selected_bounds.max_y
        ):
            continue
        multiplier = 2 if rule.enclosing_age_double_after < neighbor.age else 1
        return NeighborBoundsDecision(
            ContactBounds(
                candidate_bounds.min_x - rule.min_x_adjustment * multiplier,
                candidate_bounds.min_y - rule.min_y_adjustment * multiplier,
                candidate_bounds.max_x - rule.max_x_adjustment * multiplier,
                candidate_bounds.max_y - rule.max_y_adjustment * multiplier,
            ),
            index,
            multiplier,
        )
    return NeighborBoundsDecision(candidate_bounds, None, 0)


@dataclass(frozen=True)
class OutputOverrideInput:
    """Structurally named inputs consumed by FUN_180049880."""

    age: int
    original_code: int
    current_scores: tuple[float, float, float, float]
    previous_scores_newest_first: tuple[tuple[float, float, float, float], ...]
    context_range_active: bool = False
    pen_source_mode: int = 0
    pen_distance_squared: float = 0.0
    touches_sensor_edge: bool = False
    touches_sensor_corner: bool = False
    global_context_active: bool = False
    accumulated_metric_50: float = 0.0
    counter_254: int = 0
    region_excluded: bool = False
    metric_54: float = 0.0
    level_signal: float = 1.0
    counter_250: int = 0
    external_mode: bool = False
    external_predicate: bool = False


@dataclass(frozen=True)
class OutputOverrideDecision:
    code: int
    triggered: tuple[str, ...]


def apply_output_code_override(
    lifecycle: ProjectLifecycle, inputs: OutputOverrideInput
) -> OutputOverrideDecision:
    """Mirror FUN_180049880 without assigning speculative semantic labels."""
    if inputs.age < 0:
        raise ValueError("track age must be non-negative")
    current = _scores(inputs.current_scores)
    previous = tuple(_scores(scores) for scores in inputs.previous_scores_newest_first)
    original = inputs.original_code
    code = original
    triggered: list[str] = []
    age_minimum = lifecycle.override_age_minimum
    age_maximum = lifecycle.override_age_maximum
    if inputs.context_range_active:
        age_minimum += lifecycle.override_context_age_adjustment
        age_maximum += lifecycle.override_context_age_adjustment

    if original == 4 and age_minimum <= inputs.age <= age_maximum:
        required_previous = max(0, min(inputs.age, HISTORY_CAPACITY) - 1)
        if len(previous) < required_previous:
            raise ValueError(
                f"output override requires {required_previous} previous score samples"
            )
        score1_sum = 0.0
        score2_sum = 0.0
        score3_sum = 0.0
        skipped = 0
        for scores in previous[:required_previous]:
            if (
                scores[2] == OVERRIDE_DISABLED_SCORE
                and scores[1] == OVERRIDE_DISABLED_SCORE
                and scores[3] == OVERRIDE_DISABLED_SCORE
            ):
                skipped += 1
                continue
            score1_sum += scores[1]
            score2_sum += scores[2]
            score3_sum += scores[3]

        divisor = required_previous - skipped
        if divisor > 0:
            average_score1 = score1_sum / divisor
            average_score2 = score2_sum / divisor
            average_score3 = score3_sum / divisor
            score2_floor = (
                lifecycle.override_score2_floor_without_pen
                if inputs.pen_source_mode == 0
                else lifecycle.override_score2_floor_with_pen
            )
            pen_distance_ok = (
                inputs.pen_source_mode != 1
                or lifecycle.override_pen_distance_squared
                < inputs.pen_distance_squared
            )
            margin = lifecycle.override_default_margin
            if inputs.touches_sensor_corner:
                margin = lifecycle.override_candidate_margin + 5
            elif inputs.touches_sensor_edge:
                margin = lifecycle.override_candidate_margin
            elif inputs.pen_source_mode == 1:
                margin = lifecycle.override_pen_margin
            elif inputs.global_context_active:
                margin = lifecycle.override_context_margin
            if (
                inputs.age > 0
                and OVERRIDE_AVERAGE_METRIC_LIMIT
                < inputs.accumulated_metric_50 / inputs.age
            ):
                margin += 3

            if (
                score2_floor <= average_score2
                and pen_distance_ok
                and average_score3 < average_score2
                and margin < average_score2 - average_score1
                and lifecycle.override_minimum_counter <= inputs.counter_254
                and not inputs.region_excluded
                and inputs.metric_54 <= 4.0
                and OVERRIDE_LEVEL_SIGNAL_MINIMUM <= inputs.level_signal
            ):
                code = 2
                triggered.append("history_code2")

    # The DLL retains the entry code in fVar1, so this block can overwrite the
    # preceding code-two decision when the original code was four.
    if original == 4 and 2 < inputs.age:
        if not previous:
            raise ValueError("output override requires the previous score sample")
        prior = previous[0]
        low_current = all(
            current[index] <= OVERRIDE_LOW_SCORE_LIMIT for index in (0, 1, 2)
        ) and current[3] <= lifecycle.override_score3_floor
        low_previous = all(
            prior[index] <= OVERRIDE_LOW_SCORE_LIMIT for index in (0, 1, 2)
        ) and prior[3] <= lifecycle.override_score3_floor
        if low_current and low_previous:
            code = 1
            triggered.append("two_low_samples_code1")

    force_age = lifecycle.override_force_age
    if (
        inputs.external_mode
        and inputs.external_predicate
        and original == 4
        and inputs.touches_sensor_edge
        and 49 < force_age
    ):
        force_age = 50
    if (
        lifecycle.override_force_counter <= inputs.counter_250
        and force_age < inputs.age
    ):
        code = 1
        triggered.append("age_counter_code1")

    return OutputOverrideDecision(code, tuple(triggered))


@dataclass(frozen=True)
class FingerClassPolicyInput:
    """Proven non-pen inputs to FUN_180041150 after its score gate.

    ``fallback_feature_profile`` is candidate `+0x43`, set by FUN_180041fd8
    when ordinary component-feature extraction is bypassed at the recovered
    point-count limits. The two final class-three inputs retain their proven
    frame-level and runtime-descriptor origins.
    """

    age: int
    old_class: int
    proposed_class: int
    score_gate_accepted: bool
    point_count: int
    level_signal: float
    local_context_active: bool
    counter_254: int
    output_override: OutputOverrideInput
    special_pair_limit_active: bool = False
    fallback_feature_profile: bool = False
    frame_level_exceeds_limit: bool = False
    descriptor_context_demotion_enabled: bool = False


@dataclass(frozen=True)
class FingerClassPolicyDecision:
    code: int
    score_gate_accepted: bool
    transition_accepted: bool
    reasons: tuple[str, ...]
    override_triggers: tuple[str, ...]


def apply_finger_class_policy(
    lifecycle: ProjectLifecycle, inputs: FingerClassPolicyInput
) -> FingerClassPolicyDecision:
    """Mirror FUN_180041150's ordinary finger-only post-score policy.

    The optional external-mode and pen-proximity branches are intentionally
    outside this function. Project 0x0c83 disables the later pen-proximity
    force in its PSDB, and the external policy is guarded by a separate
    runtime mode. Everything from the class point-count gate through the
    final class-three demotion is retained here in Windows order.
    """
    if inputs.age < 0:
        raise ValueError("track age must be non-negative")
    old_class = _old_class_index(inputs.old_class)
    proposed = _class_index(inputs.proposed_class)
    if inputs.point_count < 0:
        raise ValueError("point count must not be negative")
    if inputs.counter_254 < 0:
        raise ValueError("counter must not be negative")
    if inputs.output_override.age != inputs.age:
        raise ValueError("override age does not match policy age")
    if inputs.output_override.original_code != old_class:
        raise ValueError("override entry code does not match old class")
    if inputs.output_override.pen_source_mode != 0:
        raise ValueError("finger-only policy cannot consume a pen source")
    if inputs.output_override.external_mode:
        raise ValueError("finger-only policy cannot consume external mode")

    accepted = bool(inputs.score_gate_accepted)
    reasons: list[str] = []
    minimum = lifecycle.class_point_count_minimums[proposed]
    maximum = lifecycle.class_point_count_maximums[proposed]
    if accepted and not minimum <= inputs.point_count <= maximum:
        accepted = False
        reasons.append("class_point_count")

    point_limit = (
        SINGLE_PAIR_CODE1_POINT_LIMIT
        if inputs.special_pair_limit_active
        else NEW_CONTACT_CODE1_POINT_LIMIT
    )
    if (
        accepted
        and inputs.age >= 2
        and old_class == UNCLASSIFIED
        and proposed == 1
        and inputs.point_count <= point_limit
    ):
        accepted = False
        reasons.append("new_code1_too_small")
    elif (
        accepted
        and inputs.age >= 2
        and old_class == 0
        and proposed == 1
        and inputs.point_count < ESTABLISHED_CODE1_POINT_MINIMUM
    ):
        accepted = False
        reasons.append("class0_code1_too_small")

    if (
        accepted
        and inputs.age >= 2
        and old_class == UNCLASSIFIED
        and proposed == 3
        and inputs.level_signal < lifecycle.unclassified_code3_level_threshold
        and inputs.age < lifecycle.unclassified_code3_age_release
    ):
        accepted = False
        reasons.append("new_code3_level_age")

    if (
        accepted
        and inputs.local_context_active
        and old_class == UNCLASSIFIED
        and proposed == 0
        and inputs.counter_254 < 3
    ):
        accepted = False
        reasons.append("new_code0_context_counter")

    override_triggers: tuple[str, ...] = ()
    if accepted:
        code = proposed
    else:
        code = old_class
        override = apply_output_code_override(lifecycle, inputs.output_override)
        code = override.code
        override_triggers = override.triggered
        reasons.append("output_override")

    if inputs.fallback_feature_profile:
        code = 1
        reasons.append("fallback_profile_code1")
    if code == 3 and (
        inputs.frame_level_exceeds_limit
        or (
            inputs.descriptor_context_demotion_enabled
            and inputs.local_context_active
        )
    ):
        code = UNCLASSIFIED
        reasons.append("class3_demoted")

    return FingerClassPolicyDecision(
        code,
        inputs.score_gate_accepted,
        accepted,
        tuple(reasons),
        override_triggers,
    )


def uses_fallback_feature_profile(
    lifecycle: ProjectLifecycle, *, point_count: int, local_context_active: bool
) -> bool:
    """Mirror FUN_180041fd8's candidate-+0x43 point-count predicate."""
    if point_count < 0:
        raise ValueError("point count must not be negative")
    return point_count >= lifecycle.normal_feature_point_limit or (
        local_context_active
        and point_count >= lifecycle.context_feature_point_limit
    )


def frame_level_exceeds_limit(
    lifecycle: ProjectLifecycle, frame_levels: Sequence[int]
) -> bool:
    """Mirror FUN_180044648's strict frame-wide maximum predicate."""
    for value in frame_levels:
        if not 0 <= value <= 0xFFFF:
            raise ValueError("frame level must fit an unsigned short")
    maximum = max(frame_levels, default=0)
    return lifecycle.frame_level_limit < maximum


@dataclass(frozen=True)
class ContextDecision:
    scan_id: int
    remaining: int
    active: bool


class ContextWindow:
    """Mirror the bounded global context state updated by FUN_18004a1b8.

    ``arm`` represents the separately proven writer in FUN_1800468c0. Input
    flag names stay structural until their producer objects are fully mapped.
    """

    def __init__(self, maximum: int) -> None:
        if not 0 <= maximum <= 0xFFFF:
            raise ValueError("context window must fit an unsigned short")
        self.maximum = maximum
        self.remaining = 0
        self.origin_scan = 0

    def arm(self, scan_id: int) -> None:
        self.origin_scan = self._u16(scan_id)
        self.remaining = self.maximum

    @staticmethod
    def _u16(value: int) -> int:
        if not 0 <= value <= 0xFFFF:
            raise ValueError("scan id must fit an unsigned short")
        return value

    def update(
        self,
        scan_id: int,
        *,
        persistent_flag: bool,
        source_active: bool,
        frame_flag: bool,
        source_resets_window: bool,
    ) -> ContextDecision:
        scan_id = self._u16(scan_id)
        if self.remaining:
            if self.origin_scan <= scan_id:
                elapsed = scan_id - self.origin_scan
            else:
                # Exact unsigned-wrap expression: (current - origin) - 1.
                elapsed = ((scan_id - self.origin_scan) & 0xFFFF) - 1
            if self.maximum < elapsed:
                self.remaining = 0
            else:
                self.remaining = self.maximum - elapsed

        if source_active and source_resets_window:
            self.remaining = self.maximum

        active = bool(persistent_flag or self.remaining or frame_flag)
        return ContextDecision(scan_id, self.remaining, active)


@dataclass(frozen=True)
class BaseTransitionDecision:
    """Result of only the two recovered score gates in FUN_180041150.

    Windows applies additional metric ranges, environment/context overrides,
    and lifecycle rules after this point. Keeping this result explicitly named
    prevents a partial oracle from being mistaken for final output parity.
    """

    age: int
    previous_class: int
    candidate_class: int
    selected_class: int
    accepted: bool
    gate: str


class BaseClassHistory:
    """Mirror FUN_180041150's score-gate ordering for one assigned track."""

    def __init__(self, lifecycle: ProjectLifecycle) -> None:
        self.lifecycle = lifecycle
        self.age = 0
        self.current_class = UNCLASSIFIED
        self.score_history: list[tuple[float, ...]] = []

    def update(
        self, scores: Sequence[float], *, point_count: int | None = None
    ) -> BaseTransitionDecision:
        values = _scores(scores)
        self.age += 1
        self.score_history.insert(0, values)
        del self.score_history[HISTORY_CAPACITY:]

        candidate = 0
        for class_index in range(1, CLASS_COUNT):
            if values[candidate] < values[class_index]:
                candidate = class_index

        previous = self.current_class
        rule = self.lifecycle.rule(previous, candidate)
        accepted = False
        gate = "current"
        if self.age == 1:
            accepted = rule.passes_current_scores(values)
        elif self.age <= rule.initial_age_limit:
            accepted = rule.passes_current_scores(values)
            if not accepted:
                gate = "history"
                accepted = rule.passes_score_history(self.score_history)
        else:
            gate = "history"
            accepted = rule.passes_score_history(self.score_history)

        if point_count is not None:
            if point_count < 0:
                raise ValueError("point count must not be negative")
            minimum = self.lifecycle.class_point_count_minimums[candidate]
            maximum = self.lifecycle.class_point_count_maximums[candidate]
            if accepted and not minimum <= point_count <= maximum:
                accepted = False
                gate = "point_count"

        if accepted:
            self.current_class = candidate
        return BaseTransitionDecision(
            age=self.age,
            previous_class=previous,
            candidate_class=candidate,
            selected_class=self.current_class,
            accepted=accepted,
            gate=gate,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dll", type=Path)
    parser.add_argument("--project", type=lambda value: int(value, 0), default=0x0C83)
    args = parser.parse_args()
    lifecycle = ProjectLifecycle.from_dll(args.dll.read_bytes(), args.project)
    print(json.dumps(lifecycle.summary(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
