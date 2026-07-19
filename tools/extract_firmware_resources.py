#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Inspect the Denali resource records appended to the ARC firmware image.

The Surface G6 image contains a five-record resource chain after the executable:

    u8 tag; u8 marker[3] = {0, 0, 0x0e}; u32le length; u8 data[length]

The observed tags are G, H, I, J, and 0xff.  This utility validates the entire
chain before reporting hashes and embedded ZIP members.  It is static-only: it
does not communicate with the touchscreen or install firmware.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import zlib
from zipfile import BadZipFile, ZipFile


MARKER = bytes.fromhex("00 00 0e")
EXPECTED_TAGS = (0x47, 0x48, 0x49, 0x4A, 0xFF)


@dataclass(frozen=True)
class FirmwareResource:
    header_offset: int
    tag: int
    data: bytes

    @property
    def data_offset(self) -> int:
        return self.header_offset + 8


def parse_resource_chain(image: bytes, start: int) -> list[FirmwareResource]:
    records: list[FirmwareResource] = []
    offset = start

    for expected_tag in EXPECTED_TAGS:
        if offset < 0 or len(image) - offset < 8:
            raise ValueError(f"truncated resource header at offset 0x{offset:x}")

        tag = image[offset]
        marker = image[offset + 1 : offset + 4]
        length = int.from_bytes(image[offset + 4 : offset + 8], "little")
        if tag != expected_tag:
            raise ValueError(
                f"resource tag {tag:#x} at offset 0x{offset:x}; "
                f"expected {expected_tag:#x}"
            )
        if marker != MARKER:
            raise ValueError(
                f"bad resource marker {marker.hex()} at offset 0x{offset:x}"
            )

        end = offset + 8 + length
        if end > len(image):
            raise ValueError(
                f"resource {tag:#x} at offset 0x{offset:x} declares {length} "
                f"bytes but only {len(image) - offset - 8} remain"
            )
        records.append(FirmwareResource(offset, tag, image[offset + 8 : end]))
        offset = end

    return records


def find_resource_chain(image: bytes) -> list[FirmwareResource]:
    signature = bytes([EXPECTED_TAGS[0]]) + MARKER
    candidates: list[list[FirmwareResource]] = []
    offset = 0
    while True:
        offset = image.find(signature, offset)
        if offset < 0:
            break
        try:
            candidates.append(parse_resource_chain(image, offset))
        except ValueError:
            pass
        offset += 1

    if len(candidates) != 1:
        raise ValueError(
            f"expected one valid G/H/I/J/ff resource chain, found {len(candidates)}"
        )
    return candidates[0]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def describe_resource(resource: FirmwareResource) -> dict[str, object]:
    result: dict[str, object] = {
        "tag": f"0x{resource.tag:02x}",
        "header_offset": resource.header_offset,
        "data_offset": resource.data_offset,
        "bytes": len(resource.data),
        "sha256": sha256(resource.data),
    }

    try:
        with ZipFile(BytesIO(resource.data)) as archive:
            result["zip_members"] = [
                {
                    "name": info.filename,
                    "bytes": info.file_size,
                    "sha256": sha256(archive.read(info)),
                }
                for info in archive.infolist()
            ]
    except BadZipFile:
        pass

    if resource.tag == 0xFF and resource.data.startswith((b"x\x9c", b"x\xda")):
        expanded = zlib.decompress(resource.data)
        result["zlib"] = {
            "bytes": len(expanded),
            "sha256": sha256(expanded),
        }
    return result


def describe(image: bytes) -> dict[str, object]:
    records = find_resource_chain(image)
    return {
        "image_bytes": len(image),
        "image_sha256": sha256(image),
        "resources": [describe_resource(record) for record in records],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image",
        type=Path,
        help="unwrapped CFU image or extracted ARC image",
    )
    args = parser.parse_args()
    print(json.dumps(describe(args.image.read_bytes()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
