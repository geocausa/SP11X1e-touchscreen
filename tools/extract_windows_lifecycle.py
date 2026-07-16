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
    context_source_resets_window: bool
    context_regions_enabled: bool
    context_region_distance: int
    output_merge_squared_limit: float
    output_merge_disabled_limit: float
    override_score2_floor_without_source: float
    override_score2_floor_with_source: float
    override_source_distance_squared: float
    override_context_age_adjustment: int
    override_age_minimum: int
    override_age_maximum: int
    override_force_age: int
    override_force_counter: int
    override_candidate_margin: int
    override_default_margin: int
    override_context_margin: int
    override_source_margin: int
    override_minimum_counter: int
    override_score3_floor: int
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
            "context_source_resets_window": self.context_source_resets_window,
            "context_regions_enabled": self.context_regions_enabled,
            "context_region_distance": self.context_region_distance,
            "output_merge_squared_limit": self.output_merge_squared_limit,
            "output_merge_disabled_limit": self.output_merge_disabled_limit,
            "override_score2_floor_without_source": self.override_score2_floor_without_source,
            "override_score2_floor_with_source": self.override_score2_floor_with_source,
            "override_source_distance_squared": self.override_source_distance_squared,
            "override_context_age_adjustment": self.override_context_age_adjustment,
            "override_age_minimum": self.override_age_minimum,
            "override_age_maximum": self.override_age_maximum,
            "override_force_age": self.override_force_age,
            "override_force_counter": self.override_force_counter,
            "override_candidate_margin": self.override_candidate_margin,
            "override_default_margin": self.override_default_margin,
            "override_context_margin": self.override_context_margin,
            "override_source_margin": self.override_source_margin,
            "override_minimum_counter": self.override_minimum_counter,
            "override_score3_floor": self.override_score3_floor,
            "rules": [rule.summary() for rule in self.rules],
        }


@dataclass(frozen=True)
class OutputOverrideInput:
    """Structurally named inputs consumed by FUN_180049880."""

    age: int
    original_code: int
    current_scores: tuple[float, float, float, float]
    previous_scores_newest_first: tuple[tuple[float, float, float, float], ...]
    context_range_active: bool = False
    source_mode: int = 0
    source_distance_squared: float = 0.0
    candidate_flag_49: bool = False
    candidate_flag_4a: bool = False
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
                lifecycle.override_score2_floor_without_source
                if inputs.source_mode == 0
                else lifecycle.override_score2_floor_with_source
            )
            source_distance_ok = (
                inputs.source_mode != 1
                or lifecycle.override_source_distance_squared
                < inputs.source_distance_squared
            )
            margin = lifecycle.override_default_margin
            if inputs.candidate_flag_4a:
                margin = lifecycle.override_candidate_margin + 5
            elif inputs.candidate_flag_49:
                margin = lifecycle.override_candidate_margin
            elif inputs.source_mode == 1:
                margin = lifecycle.override_source_margin
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
                and source_distance_ok
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
        and inputs.candidate_flag_49
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
