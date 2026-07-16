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


# Direct float literals at 0x18003d970 and 0x180047760.
WINDOWS_DESCRIPTOR_UNIT = 0.009999999776482582
WINDOWS_EDGE_SNAP_EPSILON = 0.00009999999747378752


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


@dataclass
class OutputContact:
    """Fields used by FUN_180045228's post-output merge pass."""

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
    y_inset_pitch: float
    layout_mode: int

    def scales(self) -> tuple[float, float]:
        """Return the exact X/Y factors stored at context +0x167e0/+0x167e4."""
        x_denominator = self.x_node_count
        y_denominator = self.y_node_count - 2 * self.y_inset_count
        if self.layout_mode == 0 and self.y_inset_count == 0:
            x_denominator -= 1
            y_denominator -= 1
        if x_denominator <= 0 or y_denominator <= 0:
            raise ValueError("sensor descriptor produces a non-positive scale denominator")

        x_scale = (
            float(self.x_extent_hundredths) * WINDOWS_DESCRIPTOR_UNIT
        ) / float(x_denominator)
        y_scale = (
            float(self.y_extent_hundredths) * WINDOWS_DESCRIPTOR_UNIT
            - 2.0 * float(self.y_inset_count) * float(self.y_inset_pitch)
        ) / float(y_denominator)
        return x_scale, y_scale


def assignment_coordinate(position: float, scale: float) -> int:
    """Mirror the positive-coordinate `(short)(int)(position*scale + .5)` step."""
    if position < 0.0 or scale < 0.0:
        raise ValueError("Windows assignment coordinates must be non-negative")
    value = math.trunc(position * scale + 0.5)
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
