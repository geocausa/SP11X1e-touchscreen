#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Construct and decode the captured Windows CFU inventory transaction.

This tool never accesses hardware and never reads or emits firmware payload
records.  It models only the 16-byte offer records and responses that were
observed on the MSHW0485 firmware-update HID collection.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


CFU_OFFER_LENGTH = 16
CFU_VERSION_LENGTH = 60
CFU_COMPONENT_INFO = 0xFF
CFU_TOKEN_WINDOWS = 0xA0


def _require_length(value: bytes, length: int, name: str) -> None:
    if len(value) != length:
        raise ValueError(f"{name} must contain {length} bytes")


def build_info_offer(code: int, token: int = CFU_TOKEN_WINDOWS) -> bytes:
    if not 0 <= code <= 2:
        raise ValueError("information code must be 0, 1, or 2")
    if not 0 <= token <= 0xFF:
        raise ValueError("token must fit in one byte")
    return bytes((code, 0, CFU_COMPONENT_INFO, token)) + bytes(12)


def build_firmware_offer(source: bytes, token: int = CFU_TOKEN_WINDOWS,
                         *, force_immediate: bool = False,
                         force_ignore_version: bool = False) -> bytes:
    _require_length(source, CFU_OFFER_LENGTH, "offer")
    if not 0 <= token <= 0xFF:
        raise ValueError("token must fit in one byte")
    result = bytearray(source)
    # Component-information bits 14 and 15 are the development-only force
    # flags.  The installed production package and captured Windows request
    # leave both clear.
    if force_immediate:
        result[1] |= 0x40
    if force_ignore_version:
        result[1] |= 0x80
    result[3] = token
    return bytes(result)


@dataclass(frozen=True)
class OfferResponse:
    token: int
    reject_reason: int
    status: int
    reserved_words_zero: bool


def decode_offer_response(content: bytes) -> OfferResponse:
    _require_length(content, CFU_OFFER_LENGTH, "offer response")
    words = [int.from_bytes(content[index:index + 4], "little")
             for index in range(0, CFU_OFFER_LENGTH, 4)]
    return OfferResponse(
        token=(words[0] >> 24) & 0xFF,
        reject_reason=words[2] & 0xFF,
        status=words[3] & 0xFF,
        reserved_words_zero=(words[0] & 0x00FFFFFF) == 0 and
                            words[1] == 0 and
                            (words[2] & 0xFFFFFF00) == 0 and
                            (words[3] & 0xFFFFFF00) == 0,
    )


def offered_version(source: bytes) -> int:
    _require_length(source, CFU_OFFER_LENGTH, "offer")
    return int.from_bytes(source[4:8], "little")


def current_version(report60: bytes) -> int:
    _require_length(report60, CFU_VERSION_LENGTH, "report 0x60")
    return int.from_bytes(report60[4:8], "little")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("offer", type=Path, help="16-byte CFU offer file")
    parser.add_argument("--response", help="optional 16-byte response as hex")
    args = parser.parse_args()

    source = args.offer.read_bytes()
    wire = build_firmware_offer(source)
    print(f"source: {source.hex(' ')}")
    print(f"wire:   {wire.hex(' ')}")
    print(f"version: 0x{offered_version(source):08x}")
    if args.response:
        decoded = decode_offer_response(bytes.fromhex(args.response))
        print(f"response token=0x{decoded.token:02x} "
              f"reject_reason=0x{decoded.reject_reason:02x} "
              f"status=0x{decoded.status:02x} "
              f"reserved_zero={decoded.reserved_words_zero}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
