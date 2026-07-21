#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Reference serializers for the recovered initial Windows feedback records."""

from __future__ import annotations

import argparse
from dataclasses import dataclass


FEEDBACK_LEN = 63


@dataclass(frozen=True)
class InitialFeedbackState:
    display_bitmap: int
    stitching_flag: int
    hinge_angle: int
    fast_host_id: int

    def validate(self) -> None:
        if not 0 <= self.display_bitmap <= 0xFF:
            raise ValueError("display_bitmap is not a byte")
        if self.stitching_flag not in (0, 1):
            raise ValueError("stitching_flag is not Boolean")
        if not 0 <= self.hinge_angle <= 0xFFFFFFFF:
            raise ValueError("hinge_angle is not a u32")
        if not 0 <= self.fast_host_id <= 0xFFFF:
            raise ValueError("fast_host_id is not a u16")


def build_a1(state: InitialFeedbackState) -> bytes:
    """Serialize the initial display/posture feedback record."""
    state.validate()
    content = bytearray(FEEDBACK_LEN)
    content[0:2] = b"\x8e\xa1"
    content[2] = state.display_bitmap
    content[3] = state.stitching_flag
    content[4:8] = state.hinge_angle.to_bytes(4, "little")
    content[40:42] = state.fast_host_id.to_bytes(2, "little")
    return bytes(content)


def build_a5_initial(state: InitialFeedbackState) -> bytes:
    """Serialize Windows' initial V06 record with no current pen provider data."""
    state.validate()
    content = bytearray(FEEDBACK_LEN)
    content[0:2] = b"\x8e\xa5"
    content[2] = 0  # successful-send sequence before the first send
    content[3] = 0x02  # V06/current-feedback pending
    content[39:41] = state.fast_host_id.to_bytes(2, "little")
    content[46:48] = (0x0040).to_bytes(2, "little")
    return bytes(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display-bitmap", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--stitching-flag", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--hinge-angle", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--fast-host-id", type=lambda value: int(value, 0), required=True)
    args = parser.parse_args()
    state = InitialFeedbackState(
        args.display_bitmap,
        args.stitching_flag,
        args.hinge_angle,
        args.fast_host_id,
    )
    print("A1", build_a1(state).hex(" "))
    print("A5", build_a5_initial(state).hex(" "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
