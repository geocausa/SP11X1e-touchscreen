#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Decode the Surface G6 report-0x12 Heat container and find signal islands."""

from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
import struct


GRID_ROWS = 46
GRID_COLS = 68
GRID_SAMPLES = GRID_ROWS * GRID_COLS
WINDOWS_SIGNAL_ZERO = 180
HEAT_THRESHOLD = 9
WINDOWS_ACTIVE_MAX = WINDOWS_SIGNAL_ZERO - HEAT_THRESHOLD
WINDOWS_STRONG_MAX = 162
MIN_CONTACT_PIXELS = 3
PALM_MAX_PIXELS = 48
PALM_MAX_SPAN = 12
MAX_CONTACTS = 10
WINDOWS_NSR_CUTOFF = 655
WINDOWS_NSR_BINS = 16
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


def connected_components(
    grid: bytes, baseline: int, threshold: int = HEAT_THRESHOLD
) -> list[dict[str, float]]:
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
        rows = [index // GRID_COLS for index in pixels]
        cols = [index % GRID_COLS for index in pixels]
        weighted_row = sum((index // GRID_COLS) * strength[index] for index in pixels) / total
        weighted_col = sum((index % GRID_COLS) * strength[index] for index in pixels) / total
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
            }
        )
    components.sort(key=lambda item: item["strength"], reverse=True)
    return components


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
