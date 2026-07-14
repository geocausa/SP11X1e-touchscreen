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


@dataclass
class Section:
    offset: int
    length: int
    kind: int
    mode: int
    header_value: int
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
        output[destination : destination + count] = section.data[position : position + count]
        written[destination : destination + count] = b"\x01" * count
        position += count

    if not all(written):
        missing = written.count(0)
        raise ValueError(f"heat section leaves {missing} grid samples unwritten")
    return bytes(output)


def connected_components(grid: bytes, baseline: int, threshold: int) -> list[dict[str, float]]:
    strength = [max(0, baseline - value) for value in grid]
    active = [value >= threshold for value in strength]
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
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
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

    heat_section = next((section for section in sections if section.kind == 0x0100), None)
    if heat_section is None:
        raise ValueError("report has no 0x0100 heat section")
    grid = extract_heatmap(heat_section)
    baseline, baseline_count = Counter(grid).most_common(1)[0]
    print(
        f"grid={GRID_COLS}x{GRID_ROWS} baseline={baseline:#04x} "
        f"baseline_samples={baseline_count}/{GRID_SAMPLES} min={min(grid):#04x} max={max(grid):#04x}"
    )

    for threshold in thresholds:
        components = connected_components(grid, baseline, threshold)
        useful = [component for component in components if component["pixels"] >= 2]
        print(f"threshold={threshold} components={len(components)} useful={len(useful)}")
        for index, component in enumerate(useful[:10]):
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
