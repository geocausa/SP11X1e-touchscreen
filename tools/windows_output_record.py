#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Exact 0x38-byte contact record builder from TouchPenProcessor0C83.dll.

This is a bounded, offline representation of ``FUN_180041b80``.  Names are
semantic only where later DLL consumers prove them; otherwise they retain the
source offset or arithmetic role.  The helper does not emit Linux input events.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct


RECORD_SIZE = 0x38
FRAME_HEADER_SIZE = 4
MAX_FRAME_RECORDS = 0x22
PROFILE_FALLBACK_ONE_THRESHOLD = 0.05999999865889549
PROFILE_OTHER_THRESHOLD = 0.07500000298023224


def _u8_from_float(value: float) -> int:
    """Mirror the DLL's truncating float-to-int followed by ``& 0xff``."""
    return int(value) & 0xFF


@dataclass(frozen=True)
class OutputThresholdPolicy:
    """Project fields read at offsets +0x0c and +0xe6c..+0xe74."""

    recent_signal_baseline: float
    ordinary_level_threshold: float
    frame_flag_level_threshold: float
    frame_level_gate: int

    @classmethod
    def from_dll(cls, data: bytes, project_id: int) -> "OutputThresholdPolicy":
        """Extract the four fields from a validated project PSDB."""
        from tools.extract_windows_classifier import (
            PROJECT_CONFIG_OFFSET,
            find_project_blob,
        )

        blob_offset, blob_length = find_project_blob(data, project_id)
        required = PROJECT_CONFIG_OFFSET + 0xE76
        if required > blob_length:
            raise ValueError("PSDB is too short for output-record thresholds")
        config = blob_offset + PROJECT_CONFIG_OFFSET
        return cls(
            recent_signal_baseline=struct.unpack_from("<f", data, config + 0x0C)[0],
            ordinary_level_threshold=struct.unpack_from(
                "<f", data, config + 0xE6C
            )[0],
            frame_flag_level_threshold=struct.unpack_from(
                "<f", data, config + 0xE70
            )[0],
            frame_level_gate=struct.unpack_from("<H", data, config + 0xE74)[0],
        )


@dataclass(frozen=True)
class TrackRecordSource:
    """Track fields copied by ``FUN_180041b80``."""

    scalar_18: float
    min_x: int
    min_y: int
    max_x: int
    max_y: int
    component_point_count: int
    source_identifier_32: int
    output_age_34: int
    group_identifier_37: int
    fallback_profile_flag_43: int


@dataclass(frozen=True)
class SelectedPosition:
    x: float
    y: float
    row_identifier: int


@dataclass(frozen=True)
class OutputRecordContext:
    """Per-frame values and external predicate result used by the builder."""

    x_node_count: int
    y_node_count: int
    frame_maximum: int
    sensor_level: float
    row_remap: tuple[int, ...]
    row_lookup: tuple[int, ...]
    profile_predicate: bool
    frame_flag_f49e: bool


@dataclass(frozen=True)
class OutputRecord:
    """Every field explicitly written by the Windows 0x38-byte builder."""

    x: float
    y: float
    scalar_10: float
    sensor_index: int
    min_x: int
    min_y: int
    max_x: int
    max_y: int
    component_point_count: int
    row_identifier: int
    source_identifier_32: int
    record_type: int
    group_identifier_27: int
    original_group_identifier_28: int
    level_passed: bool
    mapped_row: int
    byte_2c: int
    recent_or_high_signal: bool
    split_flag: int
    track_index: int
    byte_34: int
    byte_35: int
    fallback_profile_flag: int

    def to_bytes(self, base: bytes | None = None) -> bytes:
        """Apply every explicit DLL write to one record-sized byte buffer.

        ``FUN_180041b80`` does not write bytes 0x08..0x0f, 0x2b, 0x2f or
        0x37.  Supplying ``base`` preserves their caller-provided contents;
        omitting it produces a canonical zero-filled offline representation,
        not a claim that the DLL itself clears those bytes.
        """
        if base is None:
            data = bytearray(RECORD_SIZE)
        elif len(base) != RECORD_SIZE:
            raise ValueError("base record must be exactly 0x38 bytes")
        else:
            data = bytearray(base)
        struct.pack_into("<ff", data, 0x00, self.x, self.y)
        struct.pack_into("<f", data, 0x10, self.scalar_10)
        struct.pack_into("<I", data, 0x14, self.sensor_index & 0xFF)
        struct.pack_into(
            "<HHHHHH",
            data,
            0x18,
            self.min_x & 0xFFFF,
            self.min_y & 0xFFFF,
            self.max_x & 0xFFFF,
            self.max_y & 0xFFFF,
            self.component_point_count & 0xFFFF,
            self.row_identifier & 0xFFFF,
        )
        struct.pack_into("<H", data, 0x24, self.source_identifier_32 & 0xFFFF)
        data[0x26] = self.record_type & 0xFF
        data[0x27] = self.group_identifier_27 & 0xFF
        data[0x28] = self.original_group_identifier_28 & 0xFF
        data[0x29] = int(self.level_passed)
        data[0x2A] = self.mapped_row & 0xFF
        data[0x2C] = self.byte_2c & 0xFF
        data[0x2D] = int(self.recent_or_high_signal)
        data[0x2E] = self.split_flag & 0xFF
        struct.pack_into("<i", data, 0x30, self.track_index)
        data[0x34] = self.byte_34 & 0xFF
        data[0x35] = self.byte_35 & 0xFF
        data[0x36] = self.fallback_profile_flag & 0xFF
        return bytes(data)


def serialize_output_frame(
    records: tuple[OutputRecord, ...],
    *,
    global_context_active: bool,
    retained_state2_count: int,
    base: bytes | None = None,
) -> bytes:
    """Serialize the outer buffer consumed by ``FUN_180049458``.

    ``FUN_1800426d8`` stores record count, global context, and the count of
    sufficiently established state-two retained records in header bytes
    zero through two.  Header byte three and each record's unwritten bytes
    remain caller-owned and are preserved when ``base`` is supplied.
    """
    if len(records) > MAX_FRAME_RECORDS:
        raise ValueError("Windows output frame cannot contain more than 34 records")
    if not 0 <= retained_state2_count <= 0xFF:
        raise ValueError("retained state-two count must fit an unsigned byte")
    required = FRAME_HEADER_SIZE + len(records) * RECORD_SIZE
    if base is None:
        data = bytearray(required)
    elif len(base) != required:
        raise ValueError("base output frame has the wrong used length")
    else:
        data = bytearray(base)

    data[0] = len(records)
    data[1] = int(global_context_active)
    data[2] = retained_state2_count
    for index, record in enumerate(records):
        start = FRAME_HEADER_SIZE + index * RECORD_SIZE
        data[start : start + RECORD_SIZE] = record.to_bytes(
            bytes(data[start : start + RECORD_SIZE])
        )
    return bytes(data)


def _selected_level_threshold(
    policy: OutputThresholdPolicy,
    track: TrackRecordSource,
    position: SelectedPosition,
    context: OutputRecordContext,
) -> float:
    if context.frame_maximum <= policy.frame_level_gate:
        if context.profile_predicate:
            if track.fallback_profile_flag_43 != 0 and position.row_identifier == 1:
                return PROFILE_FALLBACK_ONE_THRESHOLD
            return PROFILE_OTHER_THRESHOLD
        if context.frame_flag_f49e:
            return policy.frame_flag_level_threshold
    return policy.ordinary_level_threshold


def build_output_record(
    policy: OutputThresholdPolicy,
    track: TrackRecordSource,
    position: SelectedPosition,
    context: OutputRecordContext,
    *,
    track_index: int,
    sensor_index: int,
    split_flag: int = 0,
    byte_34: int = 0,
    byte_35: int = 0,
) -> OutputRecord:
    """Mirror the non-logging body of ``FUN_180041b80`` for one record."""
    if not 0 <= sensor_index <= 0xFF:
        raise ValueError("sensor index must fit an unsigned byte")
    if not 0 <= split_flag <= 0xFF:
        raise ValueError("split flag must fit an unsigned byte")
    if context.x_node_count <= 0 or context.y_node_count <= 0:
        raise ValueError("sensor dimensions must be positive")
    if len(context.row_remap) < context.y_node_count:
        raise ValueError("row remap is shorter than the sensor Y dimension")

    rounded_y = _u8_from_float(position.y + 0.5)
    if rounded_y < context.y_node_count:
        lookup_index = context.row_remap[rounded_y]
        if not 0 <= lookup_index < len(context.row_lookup):
            raise ValueError("row remap points outside the row lookup")
        mapped_row = context.row_lookup[lookup_index]
    else:
        mapped_row = 0

    if split_flag == 0:
        scalar = track.scalar_18
        record_type = 1
        min_x, min_y = track.min_x, track.min_y
        max_x, max_y = track.max_x, track.max_y
    else:
        x_byte = _u8_from_float(position.x)
        y_byte = _u8_from_float(position.y)
        min_x = 0 if x_byte == 0 else x_byte - 1
        min_y = 0 if y_byte == 0 else y_byte - 1
        max_x = x_byte if context.x_node_count == x_byte + 1 else x_byte + 1
        max_y = y_byte if context.y_node_count == y_byte + 1 else y_byte + 1
        scalar = 4.5
        record_type = 3

    level_threshold = _selected_level_threshold(policy, track, position, context)
    return OutputRecord(
        x=position.x,
        y=position.y,
        scalar_10=scalar,
        sensor_index=sensor_index,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        component_point_count=track.component_point_count,
        row_identifier=position.row_identifier,
        source_identifier_32=track.source_identifier_32,
        record_type=record_type,
        group_identifier_27=track.group_identifier_37,
        original_group_identifier_28=track.group_identifier_37,
        level_passed=level_threshold < context.sensor_level,
        mapped_row=mapped_row,
        byte_2c=0,
        recent_or_high_signal=(
            track.output_age_34 < 4
            or policy.recent_signal_baseline < context.sensor_level
        ),
        split_flag=split_flag,
        track_index=track_index,
        byte_34=byte_34,
        byte_35=byte_35,
        fallback_profile_flag=track.fallback_profile_flag_43,
    )
