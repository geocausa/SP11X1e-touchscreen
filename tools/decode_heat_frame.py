#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Decode the Surface G6 report-0x12 Heat container and find signal islands."""

from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import dataclass
import math
from pathlib import Path
import struct


GRID_ROWS = 46
GRID_COLS = 68
GRID_SAMPLES = GRID_ROWS * GRID_COLS
WINDOWS_SIGNAL_ZERO = 180
HEAT_THRESHOLD = 9
WINDOWS_ACTIVE_MAX = WINDOWS_SIGNAL_ZERO - HEAT_THRESHOLD
WINDOWS_STRONG_MAX = 162
WINDOWS_NORMAL_CENTROID_BASELINE = 171
MIN_CONTACT_PIXELS = 3
PALM_MAX_PIXELS = 48
PALM_MAX_SPAN = 12
MAX_CONTACTS = 10
WINDOWS_NSR_CUTOFF = 655
WINDOWS_NSR_BINS = 16
WINDOWS_AXIS_SCALE = 4.618800163269043
WINDOWS_SPREAD_SCALE = 6.2831854820251465
# TouchPenProcessor's byte-to-signal lookup is initialized by FUN_180043e58.
# The project-0x0c83 secondary detector then interpolates three thresholds
# between its 0.05 floor and the candidate peak less the 0.02 noise margin.
WINDOWS_LOOKUP_BASE = 0.6000000238418579
WINDOWS_LOOKUP_INTERCEPT = 1.0 - WINDOWS_LOOKUP_BASE
WINDOWS_LOOKUP_STEP = 0.002220354275777936
WINDOWS_SECONDARY_FLOOR = 0.05000000074505806
WINDOWS_SECONDARY_NOISE = 0.019999999552965164
WINDOWS_SECONDARY_SEED = 0.054999999701976776
WINDOWS_SECONDARY_FRACTIONS = (0.5, 0.75, 0.875)
WINDOWS_LOCAL_PEAK_EPSILON = 0.00009999999747378752
WINDOWS_LOCAL_PEAK_FLOOR = 0.03999999910593033
WINDOWS_LOCAL_PEAK_CAPACITY = 10
WINDOWS_HALO_PEAK_FRACTION = 0.25
WINDOWS_HALO_RING_RATIOS = (0.15000000596046448, 0.15000000596046448)
WINDOWS_HALO_EPSILON = 0.00009999999747378752
WINDOWS_HALO_UNAVAILABLE = 100.0
# Project 0x0C83 table at TouchPenProcessor configuration +0x0D90.
WINDOWS_NSR_ROW_TO_BIN = (
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
)


@dataclass
class Section:
    offset: int
    length: int
    kind: int
    mode: int
    header_value: int
    data: bytes


@dataclass
class MetadataRecord:
    offset: int
    kind: int
    flags: int
    data: bytes


@dataclass(frozen=True)
class ContextMetadataState:
    """Persistent byte written by metadata type 0x94, subtype zero.

    TouchPenProcessor's image initializes the backing global to zero.  Unlike
    type 0x07, this value persists across frames when a frame omits type 0x94.
    """

    type94_subtype0: int = 0


@dataclass(frozen=True)
class FrameContextSources:
    """Exact metadata sources copied to tracker frame +0xb771/+0xb7ea."""

    frame_b771: int
    frame_b7ea: int
    next_state: ContextMetadataState


@dataclass(frozen=True)
class HeatCalibrationPolicy:
    """Optional 16-bit Heat conversion record consumed by ``FUN_18008f058``.

    Heat sections with mode one and element width eight bypass this policy and
    are copied byte-for-byte.  The policy is consulted only for the alternate
    16-bit sparse encoding.
    """

    enabled: bool
    gain: float
    offset: float

    @classmethod
    def from_dll(cls, data: bytes, project_id: int) -> "HeatCalibrationPolicy":
        from tools.extract_windows_classifier import find_project_blob

        blob_offset, blob_length = find_project_blob(data, project_id)
        required = 0x7A1
        if required > blob_length:
            raise ValueError("PSDB is too short for Heat calibration policy")
        return cls(
            enabled=data[blob_offset + 0x7A0] != 0,
            gain=struct.unpack_from("<f", data, blob_offset + 0x798)[0],
            offset=struct.unpack_from("<f", data, blob_offset + 0x79C)[0],
        )

    def convert_u16(self, sample: int) -> int:
        """Mirror the optional ARM64 FMADD, truncation, and byte clamp."""
        if not self.enabled:
            raise ValueError("16-bit Heat calibration is disabled")
        if not 0 <= sample <= 0xFFFF:
            raise ValueError("16-bit Heat sample is outside unsigned range")
        gain = struct.unpack("<f", struct.pack("<f", self.gain))[0]
        offset = struct.unpack("<f", struct.pack("<f", self.offset))[0]
        converted = struct.unpack(
            "<f", struct.pack("<f", math.fma(float(sample), gain, offset))
        )[0]
        return min(0xFF, max(0, math.trunc(converted)))


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def extract_report(data: bytes) -> bytes:
    if data and data[0] == 0x12:
        return data
    if len(data) >= 4 and data[0] == 0x01 and data[3] == 0x12:
        return data[3:]
    raise ValueError("not a report-0x12 buffer or class-1 HID-over-SPI response")


def parse_sections(report: bytes) -> tuple[int, int, list[Section], bytes]:
    if len(report) < 10:
        raise ValueError("truncated report")
    scan_time = u16(report, 1)
    container_length = u32(report, 3)
    end = 3 + container_length
    if end > len(report):
        raise ValueError(
            f"container overruns report: end={end}, report={len(report)}"
        )

    sections: list[Section] = []
    offset = 10
    while offset < end:
        if offset + 8 > end:
            raise ValueError(f"truncated section header at {offset:#x}")
        length = u32(report, offset)
        if length < 8 or offset + length > end:
            raise ValueError(
                f"invalid section length {length:#x} at {offset:#x}, end={end:#x}"
            )
        sections.append(
            Section(
                offset=offset,
                length=length,
                kind=u16(report, offset + 4),
                mode=report[offset + 6],
                header_value=report[offset + 7],
                data=report[offset : offset + length],
            )
        )
        offset += length

    if offset != end:
        raise ValueError(f"section walk ended at {offset:#x}, expected {end:#x}")
    return scan_time, container_length, sections, report[end:]


def extract_heatmap(section: Section) -> bytes:
    if section.kind != 0x0100:
        raise ValueError(f"expected section 0x0100, got {section.kind:#06x}")
    if section.mode != 1 or section.header_value != 8:
        raise ValueError(
            f"unsupported heat encoding mode={section.mode}, header={section.header_value}"
        )

    output = bytearray(GRID_SAMPLES)
    written = bytearray(GRID_SAMPLES)
    position = 8
    while position < section.length:
        if position + 8 > section.length:
            raise ValueError("truncated heat block header")
        destination = u32(section.data, position)
        count = u32(section.data, position + 4)
        position += 8
        if position + count > section.length:
            raise ValueError("truncated heat block payload")
        if destination + count > GRID_SAMPLES:
            raise ValueError(
                f"heat block overruns grid: offset={destination}, count={count}"
            )
        if any(written[destination : destination + count]):
            raise ValueError(
                f"heat block overlaps prior data: offset={destination}, count={count}"
            )
        output[destination : destination + count] = section.data[position : position + count]
        written[destination : destination + count] = b"\x01" * count
        position += count

    if not all(written):
        missing = written.count(0)
        raise ValueError(f"heat section leaves {missing} grid samples unwritten")
    return bytes(output)


def parse_metadata_records(section: Section) -> list[MetadataRecord]:
    """Parse the exact nested stream passed to Windows' metadata dispatcher.

    The dispatcher starts at byte seven of section 0xff00, so the section's
    header-value byte is the first record type. Each record is a four-byte
    little-endian header followed by its payload.
    """
    if section.kind != 0xFF00:
        raise ValueError(f"expected section 0xff00, got {section.kind:#06x}")

    records: list[MetadataRecord] = []
    position = 7
    while position < section.length:
        if position + 4 > section.length:
            raise ValueError(f"truncated metadata header at {position:#x}")
        length = u16(section.data, position + 2)
        end = position + 4 + length
        if end > section.length:
            raise ValueError(
                f"metadata record overruns section: offset={position:#x}, "
                f"length={length}, section={section.length}"
            )
        records.append(
            MetadataRecord(
                offset=position,
                kind=section.data[position],
                flags=section.data[position + 1],
                data=section.data[position + 4 : end],
            )
        )
        position = end
    return records


def extract_context_sources(
    section: Section,
    state: ContextMetadataState = ContextMetadataState(),
    *,
    initial_type07_payload1: int = 0,
) -> FrameContextSources:
    """Apply the recovered type-0x07/type-0x94 context-byte handlers.

    ``FUN_180069d20`` accepts only a four-byte type-0x07 payload and copies
    payload byte one into internal sensor-frame +0xd8eb.  The tracker receives
    that object shifted by +0x217a, making the same byte tracker-frame +0xb771.

    ``FUN_18006bff0`` treats type 0x94 as a counted subrecord stream.  Subtype
    zero replaces a process-global byte, which ``FUN_18008f828`` copies to
    internal +0xd964 / tracker-frame +0xb7ea on every processed frame.  The
    other recovered subtypes do not change this byte.

    The DLL silently leaves the destination unchanged for a malformed type-7
    length.  ``initial_type07_payload1`` exposes that existing value instead
    of assuming how the enclosing frame object was initialized.
    """
    if not 0 <= state.type94_subtype0 <= 0xFF:
        raise ValueError("type-0x94 state must fit an unsigned byte")
    if not 0 <= initial_type07_payload1 <= 0xFF:
        raise ValueError("type-0x07 initial value must fit an unsigned byte")

    type07_payload1 = initial_type07_payload1
    type94_subtype0 = state.type94_subtype0
    for record in parse_metadata_records(section):
        if record.kind == 0x07:
            if len(record.data) == 4:
                type07_payload1 = record.data[1]
            continue
        if record.kind != 0x94:
            continue
        if not record.data:
            raise ValueError("metadata type 0x94 has no subrecord count")

        count = record.data[0]
        position = 1
        for _ in range(count):
            if position >= len(record.data):
                raise ValueError("metadata type 0x94 has a truncated subtype")
            subtype = record.data[position]
            if subtype in (0, 2):
                if position + 2 > len(record.data):
                    raise ValueError(
                        f"metadata type 0x94 subtype {subtype} is truncated"
                    )
                if subtype == 0:
                    type94_subtype0 = record.data[position + 1]
                position += 2
            elif subtype == 1:
                if position + 7 > len(record.data):
                    raise ValueError("metadata type 0x94 subtype 1 is truncated")
                position += 7
            else:
                raise ValueError(
                    f"metadata type 0x94 has unsupported subtype {subtype:#04x}"
                )

    next_state = ContextMetadataState(type94_subtype0)
    return FrameContextSources(type07_payload1, type94_subtype0, next_state)


def extract_nsr_bins(section: Section) -> tuple[int, ...] | None:
    """Return firmware TLV 0x04's per-row-group NSR values, if present."""
    matches = [record for record in parse_metadata_records(section) if record.kind == 0x04]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"expected at most one metadata type 0x04, found {len(matches)}")

    payload = matches[0].data
    if len(payload) < 4:
        raise ValueError("metadata type 0x04 has no count header")
    count = payload[0]
    if count > WINDOWS_NSR_BINS:
        raise ValueError(f"metadata type 0x04 has invalid bin count {count}")
    required = 4 + count * 4
    if len(payload) < required:
        raise ValueError(
            f"metadata type 0x04 is truncated: count={count}, "
            f"payload={len(payload)}, required={required}"
        )
    return tuple(u16(payload, 4 + index * 4) for index in range(count))


def modal_baseline(grid: bytes) -> tuple[int, int]:
    """Match the kernel's lowest-value tie break for the modal baseline."""
    histogram = Counter(grid)
    baseline = min(histogram, key=lambda value: (-histogram[value], value))
    return baseline, histogram[baseline]


def windows_signal(value: int) -> float:
    """Return the linear calibrated signal used by project 0x0c83."""
    return WINDOWS_LOOKUP_INTERCEPT - WINDOWS_LOOKUP_STEP * value


def connected_components(
    grid: bytes, baseline: int, threshold: int = HEAT_THRESHOLD
) -> list[dict[str, object]]:
    """Build the four-connected candidates used by the Windows detector.

    ``baseline`` is retained for diagnostics and API compatibility.  Windows
    does not threshold relative to the frame mode: its normal configuration
    converts the calibrated byte grid to a fixed active ceiling.  The DLL's
    lookup is linear, with its zero crossing at approximately raw value 180.
    """
    del baseline
    active_max = WINDOWS_SIGNAL_ZERO - threshold
    strength = [max(0, WINDOWS_SIGNAL_ZERO - value) for value in grid]
    active = [value <= active_max for value in grid]
    seen = [False] * GRID_SAMPLES
    components: list[dict[str, float]] = []

    for start in range(GRID_SAMPLES):
        if not active[start] or seen[start]:
            continue
        queue = deque([start])
        seen[start] = True
        pixels: list[int] = []
        while queue:
            index = queue.popleft()
            pixels.append(index)
            row, col = divmod(index, GRID_COLS)
            for dr, dc in ((-1, 0), (0, -1), (0, 1), (1, 0)):
                nr, nc = row + dr, col + dc
                if not (0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS):
                    continue
                neighbour = nr * GRID_COLS + nc
                if active[neighbour] and not seen[neighbour]:
                    seen[neighbour] = True
                    queue.append(neighbour)

        total = sum(strength[index] for index in pixels)
        signal_total = sum(windows_signal(grid[index]) for index in pixels)
        rows = [index // GRID_COLS for index in pixels]
        cols = [index % GRID_COLS for index in pixels]
        weighted_row = sum((index // GRID_COLS) * strength[index] for index in pixels) / total
        weighted_col = sum((index % GRID_COLS) * strength[index] for index in pixels) / total
        geometry_row = sum(
            (index // GRID_COLS) * windows_signal(grid[index]) for index in pixels
        ) / signal_total
        geometry_col = sum(
            (index % GRID_COLS) * windows_signal(grid[index]) for index in pixels
        ) / signal_total
        variance_row = sum(
            windows_signal(grid[index]) * ((index // GRID_COLS) - geometry_row) ** 2
            for index in pixels
        ) / signal_total
        variance_col = sum(
            windows_signal(grid[index]) * ((index % GRID_COLS) - geometry_col) ** 2
            for index in pixels
        ) / signal_total
        covariance = sum(
            windows_signal(grid[index])
            * ((index // GRID_COLS) - geometry_row)
            * ((index % GRID_COLS) - geometry_col)
            for index in pixels
        ) / signal_total
        trace = variance_row + variance_col
        discriminant = math.sqrt(
            max(0.0, (variance_row - variance_col) ** 2 + 4.0 * covariance**2)
        )
        major_eigenvalue = max(0.0, (trace + discriminant) / 2.0)
        minor_eigenvalue = max(0.0, (trace - discriminant) / 2.0)
        major_axis = max(1.0, math.sqrt(major_eigenvalue) * WINDOWS_AXIS_SCALE)
        minor_axis = max(1.0, math.sqrt(minor_eigenvalue) * WINDOWS_AXIS_SCALE)
        axis_ratio = major_axis / minor_axis
        normalized_spread = (
            trace * WINDOWS_SPREAD_SCALE / (len(pixels) - 1)
            if len(pixels) >= 2
            else 1.0
        )
        components.append(
            {
                "pixels": float(len(pixels)),
                "strength": float(total),
                "peak_value": float(min(grid[index] for index in pixels)),
                "row": weighted_row,
                "col": weighted_col,
                "x32767": weighted_col * 32767.0 / (GRID_COLS - 1),
                "y32767": weighted_row * 32767.0 / (GRID_ROWS - 1),
                "row_min": float(min(rows)),
                "row_max": float(max(rows)),
                "col_min": float(min(cols)),
                "col_max": float(max(cols)),
                "variance_row": variance_row,
                "variance_col": variance_col,
                "covariance": covariance,
                "major_axis": major_axis,
                "minor_axis": minor_axis,
                "axis_ratio": axis_ratio,
                "normalized_spread": normalized_spread,
                # Retained for faithful secondary-detector and halo passes.
                # Command-line output deliberately does not expose this list.
                "pixel_indices": tuple(pixels),
            }
        )
    components.sort(key=lambda item: item["strength"], reverse=True)
    return components


def phase76_output_centroid(
    grid: bytes, component: dict[str, object]
) -> tuple[int, int]:
    """Mirror the kernel's fixed-point normal FUN_180047078 centroid branch.

    Project 0x0c83 selects level-table index 171 when the captured ordinary
    context flags are clear. The linear signal scale cancels from the weighted
    ratio, leaving integer weights ``171 - raw``. Assignment continues to use
    the detector centroid; this result is only the final Linux output point.
    """
    pixels = tuple(int(index) for index in component["pixel_indices"])
    weighted_x = 0
    weighted_y = 0
    total = 0
    for index in pixels:
        value = grid[index]
        if value >= WINDOWS_NORMAL_CENTROID_BASELINE:
            continue
        weight = WINDOWS_NORMAL_CENTROID_BASELINE - value
        row, column = divmod(index, GRID_COLS)
        weighted_x += column * weight
        weighted_y += row * weight
        total += weight
    if not total:
        return int(component["x32767"]), int(component["y32767"])
    return (
        weighted_x * 32767 // (total * (GRID_COLS - 1)),
        weighted_y * 32767 // (total * (GRID_ROWS - 1)),
    )


def secondary_detector_features(
    grid: bytes, component: dict[str, object]
) -> tuple[int, int, int, int, int, int]:
    """Mirror the three project-0x0c83 component reruns.

    FUN_180048838 derives three candidate-local thresholds. FUN_180047a98,
    FUN_180047cf8 and FUN_180045d98 then relabel four-connected pixels from
    the original candidate, merge equivalences, and retain islands with more
    than two cells or a peak above the 0.055 strong-seed threshold.
    """
    pixels = set(component["pixel_indices"])
    peak_signal = windows_signal(int(component["peak_value"]))
    results: list[int] = []

    # FUN_180041fd8 initializes every rerun to the undivided candidate. It
    # only invokes FUN_180048838 for a sufficiently strong, bounded blob.
    area = (
        (int(component["col_max"]) - int(component["col_min"]) + 1)
        * (int(component["row_max"]) - int(component["row_min"]) + 1)
    )
    if area >= 0x4E3 or peak_signal <= WINDOWS_SECONDARY_FLOOR + WINDOWS_SECONDARY_NOISE:
        point_count = int(component["pixels"])
        return (1, point_count, 1, point_count, 1, point_count)

    for fraction in WINDOWS_SECONDARY_FRACTIONS:
        threshold = WINDOWS_SECONDARY_FLOOR + (
            peak_signal - WINDOWS_SECONDARY_NOISE - WINDOWS_SECONDARY_FLOOR
        ) * fraction
        cutoff = int(
            ((1.0 - threshold) - WINDOWS_LOOKUP_BASE) / WINDOWS_LOOKUP_STEP + 0.5
        ) & 0xFF
        eligible = {index for index in pixels if grid[index] <= cutoff}
        islands: list[list[int]] = []

        while eligible:
            start = eligible.pop()
            queue = deque([start])
            island = [start]
            while queue:
                index = queue.popleft()
                row, col = divmod(index, GRID_COLS)
                for dr, dc in ((-1, 0), (0, -1), (0, 1), (1, 0)):
                    nr, nc = row + dr, col + dc
                    neighbour = nr * GRID_COLS + nc
                    if (
                        0 <= nr < GRID_ROWS
                        and 0 <= nc < GRID_COLS
                        and neighbour in eligible
                    ):
                        eligible.remove(neighbour)
                        queue.append(neighbour)
                        island.append(neighbour)

            island_peak = windows_signal(min(grid[index] for index in island))
            if len(island) > 2 or island_peak > WINDOWS_SECONDARY_SEED:
                islands.append(island)

        results.extend((len(islands), max(map(len, islands), default=0)))

    return tuple(results)  # type: ignore[return-value]


def local_peak_counts(
    grid: bytes, component: dict[str, object]
) -> tuple[int, int]:
    """Mirror candidate ``+0x4d/+0x4e`` from FUN_180040438/180041fd8.

    Windows scans the component in row-major order. A sample is a local peak
    when all four neighbours are lower, or when exactly three are lower and
    the remaining near-equal neighbour loses the signal/linear-index tie.
    Candidate ``+0x4d`` is capped at ten peaks. Candidate ``+0x4e`` counts the
    retained peaks whose signal is strictly greater than 0.04.
    """
    peaks: list[int] = []
    for index in sorted(component["pixel_indices"]):
        row, col = divmod(index, GRID_COLS)
        current = windows_signal(grid[index])
        lower = 0
        near_equal: list[tuple[float, int]] = []
        for dr, dc in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nr, nc = row + dr, col + dc
            if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
                neighbour_index = nr * GRID_COLS + nc
                neighbour = windows_signal(grid[neighbour_index])
            else:
                neighbour_index = -1
                neighbour = 0.0
            if neighbour + WINDOWS_LOCAL_PEAK_EPSILON < current:
                lower += 1
            elif abs(current - neighbour) < WINDOWS_LOCAL_PEAK_EPSILON:
                near_equal.append((neighbour, neighbour_index))

        selected = lower == 4
        if lower == 3 and len(near_equal) == 1:
            neighbour, neighbour_index = near_equal[0]
            selected = neighbour < current or (
                neighbour == current and index < neighbour_index
            )
        if selected and len(peaks) < WINDOWS_LOCAL_PEAK_CAPACITY:
            peaks.append(index)

    strong = sum(
        windows_signal(grid[index]) > WINDOWS_LOCAL_PEAK_FLOOR for index in peaks
    )
    return len(peaks), strong


def halo_ratio(grid: bytes, component: dict[str, object]) -> float:
    """Mirror FUN_1800432a0/FUN_1800434d8's bounded two-ring walk."""
    col_min = int(component["col_min"])
    col_max = int(component["col_max"])
    row_min = int(component["row_min"])
    row_max = int(component["row_max"])
    if col_max - col_min + 1 >= 11 or row_max - row_min + 1 >= 11:
        return WINDOWS_HALO_UNAVAILABLE

    core = set(component["pixel_indices"])
    peak_signal = windows_signal(int(component["peak_value"]))
    peak_threshold = peak_signal * WINDOWS_HALO_PEAK_FRACTION
    # Windows uses a fixed 16x16 scratch tile with a three-cell border:
    # 0=core, 1..3=walk depth, 4=available background, 5=unavailable.
    state = [[5 for _ in range(16)] for _ in range(16)]
    origin_col = col_min - 3
    origin_row = row_min - 3

    for row in range(max(0, row_min - 3), min(GRID_ROWS - 1, row_max + 3) + 1):
        for col in range(max(0, col_min - 3), min(GRID_COLS - 1, col_max + 3) + 1):
            local_row = row - origin_row
            local_col = col - origin_col
            index = row * GRID_COLS + col
            if index in core:
                state[local_row][local_col] = 0
            elif grid[index] <= WINDOWS_ACTIVE_MAX:
                # A neighbouring primary candidate is not halo background.
                state[local_row][local_col] = 5
            else:
                state[local_row][local_col] = 4

    neighbours = ((-1, 0), (0, -1), (1, 0), (0, 1))
    for row in range(row_min, row_max + 1):
        for col in range(col_min, col_max + 1):
            local_row = row - origin_row
            local_col = col - origin_col
            if state[local_row][local_col] != 0:
                continue
            for dc, dr in neighbours:
                nr, nc = row + dr, col + dc
                lr, lc = nr - origin_row, nc - origin_col
                if (
                    0 <= nr < GRID_ROWS
                    and 0 <= nc < GRID_COLS
                    and state[lr][lc] == 4
                    and windows_signal(grid[nr * GRID_COLS + nc]) > peak_threshold
                ):
                    state[lr][lc] = 1

    halo_energy = 0.0
    for radius, ring_ratio in enumerate(WINDOWS_HALO_RING_RATIOS, start=1):
        row_start = max(0, row_min - radius)
        row_end = min(GRID_ROWS - 1, row_max + radius)
        col_start = max(0, col_min - radius)
        col_end = min(GRID_COLS - 1, col_max + radius)
        for row in range(row_start, row_end + 1):
            for col in range(col_start, col_end + 1):
                local_row = row - origin_row
                local_col = col - origin_col
                if state[local_row][local_col] > radius:
                    continue
                current = windows_signal(grid[row * GRID_COLS + col])
                for dc, dr in neighbours:
                    nr, nc = row + dr, col + dc
                    lr, lc = nr - origin_row, nc - origin_col
                    if not (
                        0 <= nr < GRID_ROWS
                        and 0 <= nc < GRID_COLS
                        and state[lr][lc] == 4
                    ):
                        continue
                    neighbour = windows_signal(grid[nr * GRID_COLS + nc])
                    if (
                        neighbour < peak_threshold
                        and current > neighbour
                        and current != 0.0
                        and neighbour / current > ring_ratio - WINDOWS_HALO_EPSILON
                    ):
                        state[lr][lc] = radius + 1
                        halo_energy += neighbour

    return halo_energy / peak_signal if peak_signal != 0.0 else WINDOWS_HALO_UNAVAILABLE


def windows_classifier_features(
    grid: bytes, component: dict[str, object]
) -> tuple[float, ...]:
    """Assemble the ten inputs consumed by FUN_1800406a8."""
    secondary = secondary_detector_features(grid, component)
    return (
        float(component["pixels"]),
        float(secondary[1]),
        float(secondary[3]),
        float(secondary[5]),
        float(secondary[0]),
        float(secondary[2]),
        float(secondary[4]),
        float(component["axis_ratio"]),
        float(component["normalized_spread"]),
        halo_ratio(grid, component),
    )


def accepted_contacts(
    grid: bytes,
    baseline: int,
    threshold: int = HEAT_THRESHOLD,
    nsr_bins: tuple[int, ...] | None = None,
) -> tuple[list[dict[str, float]], int]:
    """Apply the same minimum-size, palm, and ten-contact bounds as the driver."""
    accepted: list[dict[str, float]] = []
    palm_rejections = 0
    for component in connected_components(grid, baseline, threshold):
        pixels = int(component["pixels"])
        row_span = int(component["row_max"] - component["row_min"] + 1)
        col_span = int(component["col_max"] - component["col_min"] + 1)
        peak_value = int(component["peak_value"])
        if pixels < MIN_CONTACT_PIXELS and peak_value > WINDOWS_STRONG_MAX:
            continue
        if nsr_bins is not None:
            sensor_row = int(component["row"] + 0.5)
            if 0 <= sensor_row < len(WINDOWS_NSR_ROW_TO_BIN):
                nsr_bin = WINDOWS_NSR_ROW_TO_BIN[sensor_row]
                if nsr_bin < len(nsr_bins) and nsr_bins[nsr_bin] > WINDOWS_NSR_CUTOFF:
                    continue
        if (
            pixels > PALM_MAX_PIXELS
            or row_span > PALM_MAX_SPAN
            or col_span > PALM_MAX_SPAN
        ):
            palm_rejections += 1
            continue
        accepted.append(component)
    return accepted[:MAX_CONTACTS], palm_rejections


def decode(path: Path, thresholds: list[int]) -> None:
    report = extract_report(path.read_bytes())
    scan_time, container_length, sections, trailer = parse_sections(report)
    print(f"file={path}")
    print(
        f"report_length={len(report)} scan_time={scan_time} "
        f"container_length={container_length} trailer_length={len(trailer)}"
    )
    for section in sections:
        print(
            f"section offset={section.offset:#x} length={section.length} "
            f"kind={section.kind:#06x} mode={section.mode} header={section.header_value}"
        )

    metadata_section = next((section for section in sections if section.kind == 0xFF00), None)
    nsr_bins = extract_nsr_bins(metadata_section) if metadata_section is not None else None

    heat_section = next((section for section in sections if section.kind == 0x0100), None)
    if heat_section is None:
        raise ValueError("report has no 0x0100 heat section")
    grid = extract_heatmap(heat_section)
    baseline, baseline_count = modal_baseline(grid)
    print(
        f"grid={GRID_COLS}x{GRID_ROWS} baseline={baseline:#04x} "
        f"baseline_samples={baseline_count}/{GRID_SAMPLES} min={min(grid):#04x} max={max(grid):#04x}"
    )

    for threshold in thresholds:
        components = connected_components(grid, baseline, threshold)
        useful = [component for component in components if component["pixels"] >= 2]
        accepted, palm_rejections = accepted_contacts(
            grid, baseline, threshold, nsr_bins=nsr_bins
        )
        print(
            f"threshold={threshold} active_max={WINDOWS_SIGNAL_ZERO - threshold} "
            f"components={len(components)} useful={len(useful)} "
            f"accepted={len(accepted)} palm_rejections={palm_rejections}"
        )
        if nsr_bins is not None:
            print(
                f"  nsr_bins={','.join(str(value) for value in nsr_bins)} "
                f"cutoff={WINDOWS_NSR_CUTOFF}"
            )
        for index, component in enumerate(accepted):
            print(
                "  "
                f"#{index} pixels={int(component['pixels'])} strength={int(component['strength'])} "
                f"sensor=({component['col']:.2f},{component['row']:.2f}) "
                f"logical=({component['x32767']:.0f},{component['y32767']:.0f}) "
                f"axis_ratio={component['axis_ratio']:.4f} "
                f"spread={component['normalized_spread']:.4f} "
                f"box=({int(component['col_min'])},{int(component['row_min'])})-"
                f"({int(component['col_max'])},{int(component['row_max'])})"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames", type=Path, nargs="+")
    parser.add_argument("--thresholds", type=int, nargs="+", default=[4, 8, 12, 20])
    args = parser.parse_args()
    for index, path in enumerate(args.frames):
        if index:
            print()
        decode(path, args.thresholds)


if __name__ == "__main__":
    main()
