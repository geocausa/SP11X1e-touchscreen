#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Unwrap a Microsoft CFU payload into its contiguous addressed image.

The Surface G6 payload is a stream of records:

    little-endian u32 destination offset
    u8 data length
    data[length]

This utility validates monotonic, non-overlapping records before emitting an
image suitable for hashing, string analysis, or raw import into Ghidra.  It
does not communicate with the touchscreen and cannot install firmware.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True)
class CfuRecord:
    file_offset: int
    address: int
    data: bytes


def parse_records(payload: bytes) -> list[CfuRecord]:
    records: list[CfuRecord] = []
    offset = 0
    expected_address = 0

    while offset < len(payload):
        if len(payload) - offset < 5:
            raise ValueError(f"truncated record header at file offset 0x{offset:x}")

        address = int.from_bytes(payload[offset : offset + 4], "little")
        length = payload[offset + 4]
        if not length:
            raise ValueError(f"zero-length record at file offset 0x{offset:x}")
        if address != expected_address:
            raise ValueError(
                f"non-contiguous address 0x{address:x} at file offset 0x{offset:x}; "
                f"expected 0x{expected_address:x}"
            )

        end = offset + 5 + length
        if end > len(payload):
            raise ValueError(
                f"record at file offset 0x{offset:x} declares {length} bytes "
                f"but only {len(payload) - offset - 5} remain"
            )

        data = payload[offset + 5 : end]
        records.append(CfuRecord(offset, address, data))
        expected_address += length
        offset = end

    return records


def unwrap(payload: bytes) -> bytes:
    records = parse_records(payload)
    return b"".join(record.data for record in records)


def describe(payload: bytes) -> dict[str, object]:
    records = parse_records(payload)
    image = b"".join(record.data for record in records)
    return {
        "container_bytes": len(payload),
        "container_sha256": hashlib.sha256(payload).hexdigest(),
        "record_count": len(records),
        "first_address": records[0].address if records else None,
        "last_address": records[-1].address if records else None,
        "last_record_length": len(records[-1].data) if records else None,
        "image_bytes": len(image),
        "image_sha256": hashlib.sha256(image).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("--output", type=Path, help="write the validated raw image")
    args = parser.parse_args()

    payload = args.payload.read_bytes()
    image = unwrap(payload)
    if args.output:
        args.output.write_bytes(image)
    print(json.dumps(describe(payload), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
