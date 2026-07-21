#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Validate the recovered SP11 Windows device-config provider values."""

from __future__ import annotations

import argparse


REPORT60_LENGTH = 60
REPORT56_IDENTITY_OFFSETS = (20, 24, 28, 32, 36, 40)


def report56_identity_from_report60(content: bytes) -> bytes:
    """Extract the six report-0x56 Usage-0x03 bytes mirrored by report 0x60."""
    if len(content) != REPORT60_LENGTH:
        raise ValueError(f"report 0x60 must contain {REPORT60_LENGTH} bytes")
    return bytes(content[offset] for offset in REPORT56_IDENTITY_OFFSETS)


def build_report56(identity: bytes, flag: int) -> bytes:
    if len(identity) != 6:
        raise ValueError("report 0x56 identity must contain six bytes")
    if flag not in (0, 1):
        raise ValueError("report 0x56 Usage-0x09 flag must be Boolean")
    return identity + bytes((flag,))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report60", help="60-byte GET_FEATURE 0x60 content as hex")
    parser.add_argument("--flag", type=int, choices=(0, 1), required=True)
    args = parser.parse_args()

    content = bytes.fromhex(args.report60)
    identity = report56_identity_from_report60(content)
    print(build_report56(identity, args.flag).hex(" "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
