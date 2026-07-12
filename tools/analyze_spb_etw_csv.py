#!/usr/bin/env python3
"""Summarize MSHW0485 SPB buffers exported from an ETW trace.

The input is the CSV produced by Windows Performance Analyzer for the
Microsoft-Windows-SPB-ClassExtension provider.  This tool does not open ETL
files, communicate with the touchscreen, or replay captured commands.
"""

from __future__ import annotations

import argparse
import collections
import csv
import re
from pathlib import Path


HEX_RE = re.compile(r"0x([0-9a-fA-F]+)")

OUTPUT_REPORT_TYPES = {
    0x01: "get-device-descriptor",
    0x02: "get-report-descriptor",
    0x03: "set-feature",
    0x04: "get-feature",
    0x05: "set-output-report",
    0x06: "get-input-report",
    0x07: "command",
}


def describe_e2(command: bytes) -> str:
    """Decode the public HID-over-SPI output-report header."""
    if len(command) < 8 or not command.startswith(b"\xe2\x00\x20\x00"):
        return ""

    report_type = command[4]
    content_length = int.from_bytes(command[5:7], "little")
    content_id = command[7]
    content = command[8 : 8 + content_length]
    description = OUTPUT_REPORT_TYPES.get(report_type, "reserved")
    result = (
        f"{description}, content-id=0x{content_id:02x}, "
        f"content-length={content_length}"
    )
    if report_type == 0x07 and content_id == 0x01 and content:
        power_states = {0x01: "on", 0x02: "sleep", 0x03: "off"}
        result += f", set-power={power_states.get(content[0], 'reserved')}"
    return result


def iter_buffers(path: Path):
    direction = None

    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        for line_number, row in enumerate(csv.reader(stream), 1):
            text = ",".join(row)

            if "IoSpbPayloadTdStart" in text:
                if "ToDevice" in text:
                    direction = "tx"
                elif "FromDevice" in text:
                    direction = "rx"
                else:
                    direction = None
                continue

            if "IoSpbPayloadTdBuffer" not in text or direction is None:
                continue

            matches = HEX_RE.findall(text)
            if not matches:
                continue

            # WPA puts the payload last.  Earlier hexadecimal fields are ETW
            # metadata and can have the same character length as an 8-byte
            # command, so selecting the longest match is not sufficient.
            encoded = matches[-1]
            if len(encoded) % 2:
                continue

            yield line_number, direction, bytes.fromhex(encoded)


def parse_top_level_collections(descriptor: bytes):
    offset = 0
    usage_page = 0
    usages = []
    stack = []
    collections = []

    while offset < len(descriptor):
        item_offset = offset
        prefix = descriptor[offset]
        offset += 1

        if prefix == 0xFE:
            if offset + 2 > len(descriptor):
                break
            length = descriptor[offset]
            offset += 2 + length
            continue

        length = (0, 1, 2, 4)[prefix & 3]
        item_type = (prefix >> 2) & 3
        tag = (prefix >> 4) & 15
        value = int.from_bytes(descriptor[offset : offset + length], "little")
        offset += length

        if item_type == 1 and tag == 0:  # Usage Page
            usage_page = value
        elif item_type == 1 and tag == 8:  # Report ID
            for collection in stack:
                collection["report_ids"].add(value)
        elif item_type == 2 and tag == 0:  # Usage
            usages.append(value)
        elif item_type == 0 and tag == 10:  # Collection
            collection = {
                "offset": item_offset,
                "depth": len(stack),
                "usage_page": usage_page,
                "usage": usages[-1] if usages else 0,
                "kind": value,
                "report_ids": set(),
            }
            stack.append(collection)
            if collection["depth"] == 0:
                collections.append(collection)
            usages.clear()
        elif item_type == 0 and tag == 12:  # End Collection
            if stack:
                stack.pop()
            usages.clear()
        elif item_type == 0:
            usages.clear()

    return collections


def find_report_descriptor(rx_buffers):
    for line_number, data in rx_buffers:
        if len(data) < 8:
            continue

        declared_length = int.from_bytes(data[1:3], "little")
        candidate = data[4:]
        if declared_length != len(candidate):
            continue
        if b"\x05\x0d" not in candidate or b"\xa1\x01" not in candidate:
            continue

        return line_number, candidate

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path, help="WPA-exported SPB CSV")
    parser.add_argument(
        "--write-report-descriptor",
        type=Path,
        metavar="PATH",
        help="write the device-returned HID report descriptor",
    )
    args = parser.parse_args()

    tx_commands = collections.Counter()
    rx_lengths = collections.Counter()
    input_reports = collections.Counter()
    rx_buffers = []

    for line_number, direction, data in iter_buffers(args.csv):
        if direction == "tx":
            tx_commands[data] += 1
        else:
            rx_buffers.append((line_number, data))
            rx_lengths[len(data)] += 1
            if len(data) >= 4 and data[0] == 1:
                input_reports[(data[3], len(data))] += 1

    print("RX lengths:")
    for length, count in sorted(rx_lengths.items()):
        print(f"  {length:5d} bytes: {count}")

    print("\nClass-1 report IDs:")
    for (report_id, length), count in sorted(input_reports.items()):
        print(f"  report 0x{report_id:02x}, {length:5d} bytes: {count}")

    print("\nOne-time E2 commands (observed only; not replayed):")
    for command, count in tx_commands.items():
        if command.startswith(b"\xe2\x00\x20\x00"):
            print(
                f"  count={count} {command.hex(' ')}\n"
                f"    {describe_e2(command)}"
            )

    found = find_report_descriptor(rx_buffers)
    if found is None:
        print("\nNo complete HID report descriptor found.")
        return

    line_number, descriptor = found
    print(f"\nHID report descriptor: {len(descriptor)} bytes at CSV line {line_number}")
    for index, collection in enumerate(parse_top_level_collections(descriptor)):
        report_ids = " ".join(
            f"{report_id:02x}" for report_id in sorted(collection["report_ids"])
        )
        print(
            f"  Col{index:02d}: page=0x{collection['usage_page']:04x} "
            f"usage=0x{collection['usage']:04x} reports={report_ids}"
        )

    if args.write_report_descriptor:
        args.write_report_descriptor.write_bytes(descriptor)
        print(f"Wrote {args.write_report_descriptor}")


if __name__ == "__main__":
    main()
