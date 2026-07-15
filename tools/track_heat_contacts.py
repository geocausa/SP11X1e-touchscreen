#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Deterministic reference tracker for Surface G6 heatmap contacts.

The state transitions and cost construction mirror the recovered Windows
pipeline.  Panel-specific numeric policy is named separately so that fitted
values are not confused with values recovered from the proprietary runtime
configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache
from math import hypot
from typing import Iterable, Mapping


LOGICAL_MAX = 32767
MAX_CONTACTS = 10

# Fitted policy, not recovered DLL configuration.  The Windows one-contact
# corpus has a maximum consecutive step below 900 logical units.  4096 leaves
# ample margin for faster live motion while rejecting unrelated blobs.
TRACK_MATCH_MAX = 4096
TRACK_HOLD_FRAMES = 6
# Two consecutive classifier-approved frames preserve the anti-ghost gate
# while keeping short touchscreen-keyboard taps visible long enough for the
# compositor. Weak and split candidates retain their longer evidence windows.
TRACK_CONFIRM_NORMAL = 3
TRACK_CONFIRM_WEAK = 5
TRACK_CONFIRM_SPLIT = 8
TRACK_SPLIT_RADIUS = 2048
ASSIGN_UNMATCHED_COST = 1_000_000
ASSIGN_INVALID_COST = 3_000_000

# Confirmed filter form: out = alpha * previous + (1 - alpha) * input.
# The alpha selection is a conservative panel fit pending recovery of the
# runtime project-tuning table.
SMOOTH_STATIONARY_MAX = 64
SMOOTH_SLOW_MAX = 256
SMOOTH_STATIONARY_ALPHA_NUM = 3
SMOOTH_STATIONARY_ALPHA_DEN = 4
SMOOTH_SLOW_ALPHA_NUM = 1
SMOOTH_SLOW_ALPHA_DEN = 4


class TrackState(Enum):
    ACTIVE = auto()
    COASTING = auto()


@dataclass(frozen=True)
class Measurement:
    x: int
    y: int
    pixels: int = 0
    strength: int = 0

    @classmethod
    def from_component(cls, component: Mapping[str, float]) -> "Measurement":
        return cls(
            x=round(component["x32767"]),
            y=round(component["y32767"]),
            pixels=round(component.get("pixels", 0)),
            strength=round(component.get("strength", 0)),
        )


@dataclass
class Track:
    slot: int
    raw_x: int
    raw_y: int
    output_x: int
    output_y: int
    velocity_x: int = 0
    velocity_y: int = 0
    age: int = 1
    missed: int = 0
    evidence: int = 1
    required_evidence: int = TRACK_CONFIRM_NORMAL
    confirmed: bool = False
    state: TrackState = TrackState.ACTIVE
    pixels: int = 0
    strength: int = 0

    @property
    def predicted_x(self) -> int:
        return min(LOGICAL_MAX, max(0, self.raw_x + self.velocity_x))

    @property
    def predicted_y(self) -> int:
        return min(LOGICAL_MAX, max(0, self.raw_y + self.velocity_y))


@dataclass(frozen=True)
class TrackedContact:
    slot: int
    x: int
    y: int
    raw_x: int
    raw_y: int
    age: int
    missed: int
    held: bool


def _smooth(previous: int, sample: int) -> int:
    delta = abs(sample - previous)
    if delta <= SMOOTH_STATIONARY_MAX:
        numerator, denominator = (
            SMOOTH_STATIONARY_ALPHA_NUM,
            SMOOTH_STATIONARY_ALPHA_DEN,
        )
    elif delta <= SMOOTH_SLOW_MAX:
        numerator, denominator = SMOOTH_SLOW_ALPHA_NUM, SMOOTH_SLOW_ALPHA_DEN
    else:
        return sample
    return (numerator * previous + (denominator - numerator) * sample + denominator // 2) // denominator


def minimum_cost_matches(
    tracks: list[Track], measurements: list[Measurement], gate: int
) -> list[tuple[int, int]]:
    """Return a global minimum-cost gated assignment.

    Dynamic programming is deliberately used in the offline oracle: at ten
    contacts it is small, easy to audit, and independent of the kernel's fixed
    size Hungarian implementation.  The objective first maximizes the number
    of valid matches, then minimizes total Euclidean distance.
    """
    if not tracks or not measurements:
        return []

    costs: list[list[int | None]] = []
    for track in tracks:
        row: list[int | None] = []
        for measurement in measurements:
            distance = round(
                hypot(
                    track.predicted_x - measurement.x,
                    track.predicted_y - measurement.y,
                )
            )
            row.append(distance if distance <= gate else None)
        costs.append(row)

    @lru_cache(maxsize=None)
    def solve(track_index: int, used_mask: int) -> tuple[int, int, tuple[tuple[int, int], ...]]:
        if track_index == len(tracks):
            return 0, 0, ()

        best = solve(track_index + 1, used_mask)
        for measurement_index, cost in enumerate(costs[track_index]):
            if cost is None or used_mask & (1 << measurement_index):
                continue
            matched, total, pairs = solve(
                track_index + 1, used_mask | (1 << measurement_index)
            )
            candidate = (
                matched + 1,
                total + cost,
                ((track_index, measurement_index),) + pairs,
            )
            if candidate[0] > best[0] or (
                candidate[0] == best[0] and candidate[1] < best[1]
            ):
                best = candidate
        return best

    return list(solve(0, 0)[2])


def kernel_style_matches(
    tracks: list[Track], measurements: list[Measurement], gate: int
) -> list[tuple[int, int]]:
    """Mirror the fixed-size Hungarian formulation used by the kernel port.

    This second implementation is retained for differential tests against the
    simpler dynamic-programming oracle above.
    """
    if not tracks or not measurements:
        return []
    track_count = len(tracks)
    measurement_count = len(measurements)
    size = track_count + measurement_count
    cost = [[0] * size for _ in range(size)]
    for row in range(size):
        for column in range(size):
            if row < track_count and column < measurement_count:
                distance = round(
                    hypot(
                        tracks[row].predicted_x - measurements[column].x,
                        tracks[row].predicted_y - measurements[column].y,
                    )
                )
                cost[row][column] = (
                    distance if distance <= gate else ASSIGN_INVALID_COST
                )
            elif row < track_count or column < measurement_count:
                cost[row][column] = ASSIGN_UNMATCHED_COST

    u = [0] * (size + 1)
    v = [0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)
    for i in range(1, size + 1):
        p[0] = i
        j0 = 0
        minv = [2**31 - 1] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = 2**31 - 1
            j1 = 0
            for j in range(1, size + 1):
                if used[j]:
                    continue
                reduced_cost = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if reduced_cost < minv[j]:
                    minv[j] = reduced_cost
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                elif j:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    matches = []
    for j in range(1, size + 1):
        row = p[j] - 1
        column = j - 1
        if (
            row < track_count
            and column < measurement_count
            and cost[row][column] <= gate
        ):
            matches.append((row, column))
    return matches


class ContactTracker:
    def __init__(
        self,
        *,
        max_contacts: int = MAX_CONTACTS,
        match_gate: int = TRACK_MATCH_MAX,
        hold_frames: int = TRACK_HOLD_FRAMES,
        confirm_frames: int = TRACK_CONFIRM_NORMAL,
    ) -> None:
        self.max_contacts = max_contacts
        self.match_gate = match_gate
        self.hold_frames = hold_frames
        self.confirm_frames = confirm_frames
        self.tracks: dict[int, Track] = {}

    def _confirmation_requirement(self, sample: Measurement) -> int:
        required = self.confirm_frames
        if sample.pixels < 3:
            required = max(required, TRACK_CONFIRM_WEAK)

        for track in self.tracks.values():
            if not track.confirmed or track.state is not TrackState.ACTIVE:
                continue
            if hypot(track.raw_x - sample.x, track.raw_y - sample.y) > TRACK_SPLIT_RADIUS:
                continue
            required = max(required, TRACK_CONFIRM_WEAK)
            if sample.strength * 2 <= track.strength or sample.pixels * 2 <= track.pixels:
                required = max(required, TRACK_CONFIRM_SPLIT)
        return required

    def reset(self) -> None:
        self.tracks.clear()

    def update(
        self, measurements: Iterable[Measurement | Mapping[str, float]]
    ) -> list[TrackedContact]:
        samples = [
            item if isinstance(item, Measurement) else Measurement.from_component(item)
            for item in measurements
        ][: self.max_contacts]
        slots = sorted(self.tracks)
        prior_tracks = [self.tracks[slot] for slot in slots]
        pairs = minimum_cost_matches(prior_tracks, samples, self.match_gate)
        matched_slots: set[int] = set()
        matched_samples: set[int] = set()

        for track_index, sample_index in pairs:
            track = prior_tracks[track_index]
            sample = samples[sample_index]
            old_raw_x, old_raw_y = track.raw_x, track.raw_y
            track.raw_x, track.raw_y = sample.x, sample.y
            track.velocity_x = sample.x - old_raw_x
            track.velocity_y = sample.y - old_raw_y
            track.output_x = _smooth(track.output_x, sample.x)
            track.output_y = _smooth(track.output_y, sample.y)
            track.age += 1
            if not track.confirmed:
                track.evidence += 1
                if track.evidence >= track.required_evidence:
                    track.confirmed = True
            track.missed = 0
            track.state = TrackState.ACTIVE
            track.pixels = sample.pixels
            track.strength = sample.strength
            matched_slots.add(track.slot)
            matched_samples.add(sample_index)

        for slot in slots:
            if slot in matched_slots:
                continue
            track = self.tracks[slot]
            track.missed += 1
            if track.missed > self.hold_frames:
                del self.tracks[slot]
                continue
            track.state = TrackState.COASTING
            # Keep the last point for reassociation only.  A coasting track is
            # not an observed contact and must not be emitted as input.
            track.velocity_x //= 2
            track.velocity_y //= 2

        free_slots = [slot for slot in range(self.max_contacts) if slot not in self.tracks]
        for sample_index, sample in enumerate(samples):
            if sample_index in matched_samples or not free_slots:
                continue
            slot = free_slots.pop(0)
            self.tracks[slot] = Track(
                slot=slot,
                raw_x=sample.x,
                raw_y=sample.y,
                output_x=sample.x,
                output_y=sample.y,
                pixels=sample.pixels,
                strength=sample.strength,
                required_evidence=self._confirmation_requirement(sample),
            )

        return [
            TrackedContact(
                slot=track.slot,
                x=track.output_x,
                y=track.output_y,
                raw_x=track.raw_x,
                raw_y=track.raw_y,
                age=track.age,
                missed=track.missed,
                held=track.state is TrackState.COASTING,
            )
            for track in sorted(self.tracks.values(), key=lambda item: item.slot)
            if track.state is TrackState.ACTIVE and track.confirmed
        ]
