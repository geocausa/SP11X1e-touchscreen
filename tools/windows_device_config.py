#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Validate the recovered SP11 Windows device-config provider values."""

from __future__ import annotations

import argparse


REPORT60_LENGTH = 60
REPORT56_IDENTITY_OFFSETS = (20, 24, 28, 32, 36, 40)
REPORT70_LENGTH = 1
REPORT70_HOST_HW_AUTO_BONDING = 0x01
REPORT70_SURFACE_OOB_HW_AUTO_BONDING = 0x02
REPORT70_KNOWN_MASK = (
    REPORT70_HOST_HW_AUTO_BONDING | REPORT70_SURFACE_OOB_HW_AUTO_BONDING
)


def report56_identity_from_report60(content: bytes) -> bytes:
    """Extract the captured panel-specific 0x56 correlation from report 0x60.

    The CFU header declares one component, so these later bytes are outside
    the public CFU component table.  Their repetition is useful provenance,
    not permission to treat them as standardized CFU fields or to reorder the
    Windows owners.
    """
    if len(content) != REPORT60_LENGTH:
        raise ValueError(f"report 0x60 must contain {REPORT60_LENGTH} bytes")
    return bytes(content[offset] for offset in REPORT56_IDENTITY_OFFSETS)


def build_report56(identity: bytes, flag: int) -> bytes:
    if len(identity) != 6:
        raise ValueError("report 0x56 identity must contain six bytes")
    if flag not in (0, 1):
        raise ValueError("report 0x56 Usage-0x09 flag must be Boolean")
    return identity + bytes((flag,))


def decode_report70(content: bytes) -> dict[str, bool]:
    """Decode the one-byte G6 host/device auto-bonding capability report.

    The live MSHW0485 descriptor declares two one-bit Feature usages on vendor
    page 0xfff4.  Static analysis of SurfacePenBleLcAddrAdaptationDriver.sys
    identifies usage 0x10 as HOST_HW_AUTO_BONDING_CAPABILITY and usage 0x22
    as SURFACE_OOB_HW_AUTO_BONDING_CAPABILITY.  The remaining six bits are
    descriptor-declared constant padding.
    """
    if len(content) != REPORT70_LENGTH:
        raise ValueError("report 0x70 must contain exactly one byte")
    value = content[0]
    if value & ~REPORT70_KNOWN_MASK:
        raise ValueError("report 0x70 has non-zero constant padding bits")
    return {
        "host_hw_auto_bonding": bool(value & REPORT70_HOST_HW_AUTO_BONDING),
        "surface_oob_hw_auto_bonding": bool(
            value & REPORT70_SURFACE_OOB_HW_AUTO_BONDING
        ),
    }


def build_report70(
    *, host_hw_auto_bonding: bool, surface_oob_hw_auto_bonding: bool = False
) -> bytes:
    value = 0
    if host_hw_auto_bonding:
        value |= REPORT70_HOST_HW_AUTO_BONDING
    if surface_oob_hw_auto_bonding:
        value |= REPORT70_SURFACE_OOB_HW_AUTO_BONDING
    return bytes((value,))


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
