#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Inventory SP11 vendor CCP records; this does not decode pen input.

Independent protocol inspection from the local SP11 research notes. No OEM
implementation or vendor coefficients are included. Inputs stay local.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import struct

HEAT_REPORT_IDS = frozenset((0x07, 0x08, 0x0A, 0x0B, 0x0C, 0x0D, 0x12, 0x1A, 0x1C))
MAX_BYTES = 8192
MAX_RECORDS = 100
RECORD_NAMES = {
    0x57: "pen_general", 0x58: "pen_jnr", 0x59: "pen_noise",
    0x5A: "pen_selection", 0x5B: "pen_magnitude", 0x5C: "pen_dft",
    0x5D: "pen_regions", 0x5E: "pen_antennas", 0x5F: "pen_window",
    0x62: "pen_detection", 0x63: "pen_lift", 0x80: "pen_jnr_v2",
}


@dataclass(frozen=True)
class Record:
    offset: int
    kind: int
    flags: int
    size: int
    name: str
    fields: dict[str, int]


def parse_vendor(data: bytes) -> list[Record]:
    """Parse a vendor payload after its seven-byte CapImg section header.

    Offset/size checks precede every field access. Unknown records and flags
    remain visible. Structural validity does not imply a valid pen sample.
    """
    if len(data) > MAX_BYTES:
        raise ValueError("vendor payload exceeds input bound")
    records = []
    offset = 0
    while offset < len(data):
        if data[offset] == 0xFF:
            return records
        if len(data) - offset < 4:
            raise ValueError(f"truncated CCP header at {offset}")
        kind, flags, size = struct.unpack_from("<BBH", data, offset)
        if kind == 0 and size == 0:
            return records
        if len(records) >= MAX_RECORDS:
            raise ValueError("more than 100 CCP records")
        start = offset + 4
        end = start + size
        if end > len(data):
            raise ValueError(f"CCP payload overruns section at {offset}")
        fields = {}
        if kind == 0x57:
            if size != 0x40:
                raise ValueError("unsupported pen general payload size")
            frame, timestamp, cycle, lf, hf = struct.unpack_from("<IIHBB", data, start)
            fields = dict(frame=frame, timestamp=timestamp, cycle=cycle, lf_gain=lf, hf_gain=hf)
        elif kind == 0x62:
            if size != 0x10:
                raise ValueError("unsupported pen detection payload size")
            chip, window, window_type = struct.unpack_from("<BBB", data, start + 12)
            # Preserve raw metadata; these ranges are hypotheses to check on
            # real captures, not a reason to manufacture or emit a pen event.
            fields = dict(chip=chip, window=window, window_type=window_type)
        elif kind == 0x63:
            if not size:
                raise ValueError("empty pen lift payload")
            fields = dict(reason=data[start])
        records.append(Record(offset, kind, flags, size, RECORD_NAMES.get(kind, "unknown"), fields))
        offset = end
    return records


def inspect_report(data: bytes) -> dict:
    """Inspect one report ID + scan time + CapImg container.

    Transfer padding after the declared container is counted, never parsed.
    Only the raw report envelope is accepted; no guessed byte scanning.
    """
    if len(data) > MAX_BYTES:
        raise ValueError("report exceeds input bound")
    if len(data) < 10 or data[0] not in HEAT_REPORT_IDS:
        raise ValueError("expected a complete Col02 HEAT report with report ID")
    scan_time = struct.unpack_from("<H", data, 1)[0]
    length, kind, version = struct.unpack_from("<IHB", data, 3)
    if length < 7 or length > len(data) - 3:
        raise ValueError("invalid CapImg container length")
    if kind != 0 or version != 0:
        raise ValueError("unsupported CapImg container type/version")
    end = 3 + length
    offset = 10
    sections = []
    while offset < end:
        if end - offset < 7:
            raise ValueError("truncated CapImg section header")
        size, section_kind, section_version = struct.unpack_from("<IHB", data, offset)
        if size < 7 or size > end - offset:
            raise ValueError("invalid CapImg section length")
        section_end = offset + size
        item = dict(kind=section_kind, version=section_version, size=size)
        if section_kind == 0xFF00:
            item["records"] = [asdict(r) for r in parse_vendor(data[offset + 7:section_end])]
        sections.append(item)
        offset = section_end
    return dict(report_id=data[0], scan_time=scan_time, sections=sections,
                trailing_bytes=len(data) - end, pen_receiver_implemented=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="local binary report or vendor payload")
    parser.add_argument("--format", choices=("report", "vendor"), default="report")
    args = parser.parse_args()
    try:
        with args.input.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if args.format == "vendor":
            result = dict(records=[asdict(r) for r in parse_vendor(data)],
                          pen_receiver_implemented=False)
        else:
            result = inspect_report(data)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
