#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Exact, bounded geometry helpers recovered from TouchPenProcessor0C83.dll.

These helpers cover only the arithmetic proven in FUN_18003d7a8,
FUN_1800453e8, FUN_18004a330, FUN_180041b80, and FUN_180054690.  They
intentionally do not guess the descriptor values supplied to the Windows
processor or conflate the separately blended component metric with X/Y.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct


# Direct float literals at 0x18003d970 and 0x180047760.
WINDOWS_DESCRIPTOR_UNIT = 0.009999999776482582
WINDOWS_EDGE_SNAP_EPSILON = 0.00009999999747378752
WINDOWS_SIGNAL_LOOKUP_BASE = 0.6000000238418579
WINDOWS_SIGNAL_LOOKUP_STEP = 0.002220354275777936
WINDOWS_PROFILE_BASELINE_INDEX = 178
WINDOWS_ALTERNATE_BASELINE_INDEX = 173


@dataclass(frozen=True)
class CandidateEdgeFlags:
    """Candidate boundary fields written by FUN_1800489a0."""

    edge_kind: int
    touches_sensor_edge: bool
    touches_sensor_corner: bool
    near_sensor_edge: bool


@dataclass(frozen=True)
class ProfileRegion:
    """Five-byte optional rectangle consumed by ``FUN_18004b280``."""

    enabled: bool
    min_x: int
    max_x: int
    min_y: int
    max_y: int

    @classmethod
    def from_bytes(cls, data: bytes) -> "ProfileRegion":
        if len(data) != 5:
            raise ValueError("profile region must contain exactly five bytes")
        return cls(data[0] == 1, data[1], data[2], data[3], data[4])

    def contains(self, x: float, y: float) -> bool:
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("profile coordinates must be finite")
        return bool(
            self.enabled
            and self.min_x <= x <= self.max_x
            and self.min_y <= y <= self.max_y
        )


def candidate_edge_flags(
    *,
    min_x: int,
    max_x: int,
    min_y: int,
    max_y: int,
    centroid_x: float,
    centroid_y: float,
    x_node_count: int,
    y_node_count: int,
    edge_margin: float,
    context_active: bool = False,
) -> CandidateEdgeFlags:
    """Mirror FUN_1800489a0's ordinary grid-edge and margin predicates.

    The separate layout-specific seam flag at candidate +0x4b is intentionally
    excluded because it depends on descriptor mode fields not represented by
    this bounded helper.
    """
    if x_node_count <= 0 or y_node_count <= 0:
        raise ValueError("sensor node counts must be positive")
    if not (0 <= min_x <= max_x < x_node_count):
        raise ValueError("candidate X bounds are outside the sensor grid")
    if not (0 <= min_y <= max_y < y_node_count):
        raise ValueError("candidate Y bounds are outside the sensor grid")
    if edge_margin < 0.0:
        raise ValueError("edge margin must be non-negative")

    edge_count = 0
    edge_kind = 0
    if min_x == 0:
        edge_kind = 1
        edge_count = 1
    elif max_x == x_node_count - 1:
        edge_kind = 3
        edge_count = 1

    if min_y == 0:
        edge_kind = 2
        edge_count += 1
    elif max_y == y_node_count - 1:
        edge_kind = 4
        edge_count += 1

    touches_sensor_edge = edge_count != 0
    touches_sensor_corner = edge_count >= 2
    if touches_sensor_corner:
        edge_kind = 5

    selected_margin = edge_margin + (0.5 if context_active else 0.0)
    near_sensor_edge = (
        centroid_x <= selected_margin
        or centroid_y <= selected_margin
        or float(x_node_count - 1) - selected_margin <= centroid_x
        or float(y_node_count - 1) - selected_margin <= centroid_y
    )
    return CandidateEdgeFlags(
        edge_kind,
        touches_sensor_edge,
        touches_sensor_corner,
        near_sensor_edge,
    )


@dataclass
class TrackKinematics:
    """Exact coordinate state maintained by FUN_18004a330.

    Windows stores the current candidate position directly, records the
    new-minus-old displacement, and expands running bounds.  It does not
    exponentially smooth either coordinate in this function.  The final
    normal-contact builder at FUN_180041b80 copies these stored X/Y values
    directly to its output record.
    """

    x: float
    y: float
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    age: int = 1
    min_x: float | None = None
    min_y: float | None = None
    max_x: float | None = None
    max_y: float | None = None

    def __post_init__(self) -> None:
        if self.min_x is None:
            self.min_x = self.x
        if self.min_y is None:
            self.min_y = self.y
        if self.max_x is None:
            self.max_x = self.x
        if self.max_y is None:
            self.max_y = self.y

    @property
    def predicted_x(self) -> float:
        """One-frame constant-velocity prediction used for assignment."""
        return self.x + self.velocity_x

    @property
    def predicted_y(self) -> float:
        """One-frame constant-velocity prediction used for assignment."""
        return self.y + self.velocity_y

    def update(self, candidate_x: float, candidate_y: float) -> None:
        """Apply the coordinate portion of FUN_18004a330 exactly."""
        old_x = self.x
        old_y = self.y
        self.age += 1
        self.velocity_x = candidate_x - old_x
        self.velocity_y = candidate_y - old_y
        self.x = candidate_x
        self.y = candidate_y
        self.min_x = min(float(self.min_x), candidate_x)
        self.min_y = min(float(self.min_y), candidate_y)
        self.max_x = max(float(self.max_x), candidate_x)
        self.max_y = max(float(self.max_y), candidate_y)


@dataclass(frozen=True)
class TrackScalarBlendPolicy:
    """PSDB alpha used for track +0x18's non-coordinate scalar."""

    base_alpha: float

    @classmethod
    def from_dll(cls, data: bytes, project_id: int) -> "TrackScalarBlendPolicy":
        from tools.extract_windows_classifier import (
            PROJECT_CONFIG_OFFSET,
            find_project_blob,
        )

        blob_offset, blob_length = find_project_blob(data, project_id)
        required = PROJECT_CONFIG_OFFSET + 0xEB0
        if required > blob_length:
            raise ValueError("PSDB is too short for track scalar blend policy")
        return cls(
            struct.unpack_from(
                "<f", data, blob_offset + PROJECT_CONFIG_OFFSET + 0xEAC
            )[0]
        )


def blend_track_scalar(
    policy: TrackScalarBlendPolicy,
    *,
    previous_scalar: float,
    candidate_scalar: float,
    prior_class4_counter: int,
    motion_limited: bool,
    velocity_x: float,
    velocity_y: float,
) -> float:
    """Mirror the scalar-only tail of ``FUN_18004a330``.

    This value is later copied to output record +0x10.  It is independent of
    track X/Y. ARM64 fused multiply-add operations are preserved explicitly.
    """
    if not 0 <= prior_class4_counter <= 0xFFFF:
        raise ValueError("prior class-four counter must fit an unsigned short")
    values = (
        policy.base_alpha,
        previous_scalar,
        candidate_scalar,
        velocity_x,
        velocity_y,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("track scalar inputs must be finite")
    if prior_class4_counter == 0:
        return _float32(candidate_scalar)

    alpha = _float32(policy.base_alpha)
    if motion_limited:
        vx = _float32(velocity_x)
        vy = _float32(velocity_y)
        vx_squared = _float32(vx * vx)
        squared_motion = _float32(math.fma(vy, vy, vx_squared))
        motion_alpha = _float32(squared_motion * _float32(10.0))
        if motion_alpha < alpha:
            alpha = motion_alpha

    old_weight = _float32(_float32(1.0) - alpha)
    old_part = _float32(old_weight * _float32(previous_scalar))
    return _float32(
        math.fma(_float32(candidate_scalar), alpha, old_part)
    )


@dataclass
class OutputContact:
    """Fields used by FUN_180045228's post-output merge pass.

    ``group_id`` is output-record byte +0x27.  The builder initially copies it
    from track byte +0x37; the merge pass rewrites +0x27 while leaving the
    original identifier at record +0x28 intact.
    """

    x: float
    y: float
    record_type: int
    group_id: int
    track_index: int


def merge_nearby_output_contacts(
    contacts: list[OutputContact], distance_squared_limit: float
) -> set[int]:
    """Mirror FUN_180045228's pair collection and relabelling order.

    Only record types one and three participate.  Pairs must have different
    group identifiers and a strictly smaller squared distance.  The second
    pass coalesces each later identifier into the earlier one, changes paired
    type-one records to type seven, and marks their source tracks.
    """
    if distance_squared_limit < 0.0:
        raise ValueError("merge distance-squared limit must be non-negative")

    pairs: list[tuple[int, int]] = []
    merged_tracks: set[int] = set()
    for first_index, first in enumerate(contacts):
        if first.record_type not in (1, 3):
            continue
        for second_index in range(first_index + 1, len(contacts)):
            second = contacts[second_index]
            if second.record_type not in (1, 3):
                continue
            if first.group_id == second.group_id:
                continue
            dx = first.x - second.x
            dy = first.y - second.y
            if dx * dx + dy * dy < distance_squared_limit:
                pairs.append((first_index, second_index))
                merged_tracks.add(first.track_index)
                merged_tracks.add(second.track_index)

    for first_index, second_index in pairs:
        first = contacts[first_index]
        second = contacts[second_index]
        replaced_group = second.group_id
        for contact in contacts:
            if contact.group_id == replaced_group:
                contact.group_id = first.group_id
        if first.record_type == 1:
            first.record_type = 7
        if second.record_type == 1:
            second.record_type = 7

    return merged_tracks


@dataclass(frozen=True)
class AssignmentScaleInputs:
    """Fields consumed by FUN_18003d7a8's two assignment-scale formulas.

    Names describe arithmetic roles, not an assumed HID report layout.  The
    source is the runtime sensor descriptor passed to the processor.
    """

    x_extent_hundredths: int
    y_extent_hundredths: int
    x_node_count: int
    y_node_count: int
    y_inset_count: int
    y_inset_pitch: int
    layout_mode: int

    @classmethod
    def from_dll(
        cls, data: bytes, project_id: int, sensor_index: int = 0
    ) -> "AssignmentScaleInputs":
        """Extract FUN_18008f3f8's inputs from a validated project PSDB."""
        if sensor_index < 0:
            raise ValueError("sensor index must be non-negative")
        from tools.extract_windows_classifier import find_project_blob

        blob_offset, blob_length = find_project_blob(data, project_id)
        sensor_offset = 0x38 + sensor_index * 0x34
        required = max(sensor_offset + 8, 0x6C)
        if required > blob_length:
            raise ValueError("PSDB is too short for the sensor descriptor")
        sensor = blob_offset + sensor_offset
        return cls(
            x_extent_hundredths=struct.unpack_from(
                "<I", data, blob_offset + 0x58
            )[0],
            y_extent_hundredths=struct.unpack_from(
                "<I", data, blob_offset + 0x54
            )[0],
            x_node_count=struct.unpack_from("<H", data, sensor + 0x06)[0],
            y_node_count=struct.unpack_from("<H", data, sensor + 0x04)[0],
            y_inset_count=struct.unpack_from("<H", data, blob_offset + 0x40)[0],
            y_inset_pitch=struct.unpack_from("<I", data, blob_offset + 0x64)[0],
            layout_mode=struct.unpack_from("<h", data, blob_offset + 0x42)[0],
        )

    def scales(self) -> tuple[float, float]:
        """Return the exact X/Y factors stored at context +0x167e0/+0x167e4."""
        x_denominator = self.x_node_count
        y_denominator = self.y_node_count - 2 * self.y_inset_count
        if self.layout_mode == 0 and self.y_inset_count == 0:
            x_denominator -= 1
            y_denominator -= 1
        if x_denominator <= 0 or y_denominator <= 0:
            raise ValueError("sensor descriptor produces a non-positive scale denominator")

        x_extent = _float32(
            float(self.x_extent_hundredths) * WINDOWS_DESCRIPTOR_UNIT
        )
        y_extent = _float32(
            float(self.y_extent_hundredths) * WINDOWS_DESCRIPTOR_UNIT
        )
        x_scale = _float32(x_extent / float(x_denominator))
        y_scale = _float32(
            (
                float(y_extent)
                - 2.0 * float(self.y_inset_count) * float(self.y_inset_pitch)
            )
            / float(y_denominator)
        )
        return x_scale, y_scale


def _float32(value: float) -> float:
    """Round one arithmetic stage to the DLL's IEEE-754 float precision."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def assignment_coordinate(position: float, scale: float) -> int:
    """Mirror the positive-coordinate `(short)(int)(position*scale + .5)` step."""
    if position < 0.0 or scale < 0.0:
        raise ValueError("Windows assignment coordinates must be non-negative")
    value = math.trunc(position * scale + 0.5)
    if value > 0x7FFF:
        raise ValueError("assignment coordinate does not fit the Windows signed short")
    return value


def kernel_q24_assignment_coordinate(
    weighted_position: int, strength: int, scale: float
) -> int:
    """Mirror Phase 70's integer centroid and assignment quantization.

    ``weighted_position / strength`` is the connected component centroid.
    Both the centroid and recovered float32 scale are represented in Q8.24;
    the final half-up rounding is the unsigned-positive Windows operation.
    """
    if weighted_position < 0:
        raise ValueError("weighted position must be non-negative")
    if strength <= 0:
        raise ValueError("strength must be positive")
    if scale < 0.0 or not math.isfinite(scale):
        raise ValueError("assignment scale must be finite and non-negative")
    position_q24 = (weighted_position << 24) // strength
    scale_q24 = round(scale * (1 << 24))
    value = (position_q24 * scale_q24 + (1 << 47)) >> 48
    if value > 0x7FFF:
        raise ValueError("assignment coordinate does not fit the Windows signed short")
    return value


def assignment_pair_is_valid(
    track_x: int,
    track_y: int,
    candidate_x: int,
    candidate_y: int,
    radius: float,
) -> bool:
    """Apply FUN_1800453e8's strict squared-radius acceptance predicate."""
    if radius < 0.0:
        raise ValueError("assignment radius must be non-negative")
    dx = int(track_x) - int(candidate_x)
    dy = int(track_y) - int(candidate_y)
    return dx * dx + dy * dy < radius * radius


def _roundf(value: float) -> float:
    """C roundf semantics: halfway cases round away from zero."""
    if value >= 0.0:
        return float(math.floor(value + 0.5))
    return float(math.ceil(value - 0.5))


def snap_far_edge_centroid(
    value: float, epsilon: float = WINDOWS_EDGE_SNAP_EPSILON
) -> float:
    """Mirror FUN_180054690, called only for a far-edge one-cell component.

    The caller is responsible for the exact edge predicate.  Windows snaps
    only when the weighted centroid lies within epsilon of the nearest integer.
    """
    if epsilon < 0.0:
        raise ValueError("edge snap epsilon must be non-negative")
    rounded = _roundf(value)
    if rounded + epsilon < value or value < rounded - epsilon:
        return value
    return rounded


@dataclass(frozen=True)
class ExpandedCentroidBaselineInputs:
    """The three baseline branches selected near the top of FUN_180047078."""

    reference_baseline: float
    profile_baseline_c858: float
    alternate_baseline_c844: float
    frame_maximum_exceeded: bool
    profile_predicate: bool
    processor_flag_198c8: bool
    output_flag_97: bool


def _signal_lookup(index: int) -> float:
    if not 0 <= index <= 0xFF:
        raise ValueError("signal lookup index must fit an unsigned byte")
    # ARM64 uses FMADD for base + index*step, so preserve its single rounding.
    combined = _float32(
        math.fma(
            _float32(float(index)),
            WINDOWS_SIGNAL_LOOKUP_STEP,
            WINDOWS_SIGNAL_LOOKUP_BASE,
        )
    )
    return _float32(1.0 - combined)


@dataclass(frozen=True)
class ExpandedCentroidPolicy:
    """PSDB +0xb84 fields consumed by ``FUN_180047078``."""

    admission_multiplier: float
    normal_baseline_index: int
    high_frame_baseline_index: int
    processor_override_enabled: bool

    @classmethod
    def from_dll(cls, data: bytes, project_id: int) -> "ExpandedCentroidPolicy":
        from tools.extract_windows_classifier import find_project_blob

        blob_offset, blob_length = find_project_blob(data, project_id)
        required = 0xBAD
        if required > blob_length:
            raise ValueError("PSDB is too short for expanded-centroid policy")
        record = blob_offset + 0xB84
        multiplier_source = struct.unpack_from("<H", data, record + 0x08)[0]
        return cls(
            admission_multiplier=_float32(
                float(multiplier_source) * WINDOWS_DESCRIPTOR_UNIT
            ),
            normal_baseline_index=struct.unpack_from(
                "<H", data, record + 0x10
            )[0],
            high_frame_baseline_index=struct.unpack_from(
                "<H", data, record + 0x18
            )[0],
            processor_override_enabled=data[blob_offset + 0xBAC] != 0,
        )

    def baseline_inputs(
        self,
        *,
        frame_maximum_exceeded: bool,
        profile_predicate: bool,
        output_flag_97: bool,
    ) -> ExpandedCentroidBaselineInputs:
        reference_index = (
            self.high_frame_baseline_index
            if frame_maximum_exceeded
            else self.normal_baseline_index
        )
        return ExpandedCentroidBaselineInputs(
            reference_baseline=_signal_lookup(reference_index),
            profile_baseline_c858=_signal_lookup(WINDOWS_PROFILE_BASELINE_INDEX),
            alternate_baseline_c844=_signal_lookup(
                WINDOWS_ALTERNATE_BASELINE_INDEX
            ),
            frame_maximum_exceeded=frame_maximum_exceeded,
            profile_predicate=profile_predicate,
            processor_flag_198c8=self.processor_override_enabled,
            output_flag_97=output_flag_97,
        )


def select_expanded_centroid_baseline(
    inputs: ExpandedCentroidBaselineInputs,
) -> float:
    """Mirror FUN_180047078's ordered baseline override branches."""
    if not inputs.frame_maximum_exceeded:
        if inputs.profile_predicate:
            return inputs.profile_baseline_c858
        if inputs.processor_flag_198c8 or inputs.output_flag_97:
            return inputs.alternate_baseline_c844
    return inputs.reference_baseline


def update_track_centroid_override_flag(
    *,
    current: bool,
    candidate_flag_b1: bool,
    updated_age: int,
    maximum_point_count: int,
    frame_maximum_exceeded: bool,
) -> bool:
    """Mirror the sticky track `+0x25c` writer in ``FUN_18004a330``.

    The candidate producer remains structurally named by its `+0xb1` offset;
    the track-side mutation and every numeric boundary are exact.
    """
    if updated_age < 0:
        raise ValueError("updated track age must be non-negative")
    if not 0 <= maximum_point_count <= 0xFFFF:
        raise ValueError("maximum point count must fit an unsigned short")
    return bool(
        current
        or (
            candidate_flag_b1
            and updated_age > 1
            and maximum_point_count < 5
            and not frame_maximum_exceeded
        )
    )


@dataclass(frozen=True)
class ExpandedCentroidResult:
    x: float
    y: float
    admitted_halo_cells: tuple[tuple[int, int], ...]
    weight: float


def expanded_edge_centroid(
    *,
    label_grid: tuple[tuple[int, ...], ...],
    level_index_grid: tuple[tuple[int, ...], ...],
    label_owner: tuple[int, ...],
    levels: tuple[float, ...],
    component_owner: int,
    min_x: int,
    min_y: int,
    max_x: int,
    max_y: int,
    candidate_level_index: int,
    admission_multiplier: float,
    baseline: float,
    clamp_expanded_window: bool,
) -> ExpandedCentroidResult:
    """Represent FUN_180047078's weighted component-plus-halo centroid.

    The DLL temporarily marks zero-labelled cells with 0xff while walking the
    expanded rectangle.  A zero cell is admitted exactly when an orthogonally
    adjacent member cell is above the candidate-level admission threshold.
    Expressing that final set directly avoids mutating the caller's label grid.
    Accumulation still follows the DLL's unusual interior, right-edge,
    bottom-edge, corner order so float32 rounding remains faithful.
    """
    if not label_grid or not label_grid[0]:
        raise ValueError("label grid must not be empty")
    height = len(label_grid)
    width = len(label_grid[0])
    if any(len(row) != width for row in label_grid):
        raise ValueError("label grid rows must have equal width")
    if len(level_index_grid) != height or any(
        len(row) != width for row in level_index_grid
    ):
        raise ValueError("level-index grid shape must match the label grid")
    if not (0 <= min_x <= max_x < width and 0 <= min_y <= max_y < height):
        raise ValueError("component bounds are outside the grids")
    if not 0 <= candidate_level_index < len(levels):
        raise ValueError("candidate level index is outside the level table")
    if admission_multiplier < 0.0:
        raise ValueError("admission multiplier must be non-negative")
    for row in label_grid:
        if any(not 0 <= label < len(label_owner) for label in row):
            raise ValueError("label grid contains an unmapped label")
    for row in level_index_grid:
        if any(not 0 <= index < len(levels) for index in row):
            raise ValueError("level-index grid contains an invalid index")

    left, top = min_x - 1, min_y - 1
    right, bottom = max_x + 1, max_y + 1
    if clamp_expanded_window:
        left, top = max(left, 0), max(top, 0)
        right, bottom = min(right, width - 1), min(bottom, height - 1)
    elif left < 0 or top < 0 or right >= width or bottom >= height:
        raise ValueError("unclamped expanded window crosses a sensor edge")

    def belongs(x: int, y: int) -> bool:
        return label_owner[label_grid[y][x]] == component_owner

    admission_threshold = _float32(
        _float32(levels[candidate_level_index]) * _float32(admission_multiplier)
    )
    halo: set[tuple[int, int]] = set()
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            if label_grid[y][x] != 0 or belongs(x, y):
                continue
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if not (left <= nx <= right and top <= ny <= bottom):
                    continue
                adjacent_level = _float32(levels[level_index_grid[ny][nx]])
                if belongs(nx, ny) and admission_threshold < adjacent_level:
                    halo.add((x, y))
                    break

    traversal = [
        *((x, y) for y in range(top, bottom) for x in range(left, right)),
        *((right, y) for y in range(top, bottom)),
        *((x, bottom) for x in range(left, right)),
        (right, bottom),
    ]
    sum_x = _float32(0.0)
    sum_y = _float32(0.0)
    sum_weight = _float32(0.0)
    for x, y in traversal:
        member = belongs(x, y)
        if not member and (x, y) not in halo:
            continue
        level = _float32(levels[level_index_grid[y][x]])
        weight = _float32(level - _float32(baseline))
        # The member branch adds its signed excess unconditionally.  Only the
        # temporary 0xff halo branch tests baseline < level before adding.
        if not member and weight <= 0.0:
            continue
        sum_x = _float32(sum_x + _float32(weight * float(x)))
        sum_y = _float32(sum_y + _float32(weight * float(y)))
        sum_weight = _float32(sum_weight + weight)
    if sum_weight == 0.0:
        raise ValueError("expanded centroid has zero total weight")

    x = _float32(sum_x * _float32(1.0 / sum_weight))
    y = _float32(sum_y * _float32(1.0 / sum_weight))
    if min_x == max_x == width - 1:
        x = snap_far_edge_centroid(x)
    if min_y == max_y == height - 1:
        y = snap_far_edge_centroid(y)
    return ExpandedCentroidResult(x, y, tuple(sorted(halo)), sum_weight)
