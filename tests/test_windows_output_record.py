# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import struct
import unittest

from tools.extract_windows_classifier import PROJECT_CONFIG_OFFSET
from tools.windows_output_record import (
    OutputRecordContext,
    OutputThresholdPolicy,
    SelectedPosition,
    TrackRecordSource,
    build_output_record,
    serialize_output_frame,
)


class WindowsOutputRecordTests(unittest.TestCase):
    def setUp(self):
        self.policy = OutputThresholdPolicy(0.055, 0.12, 0.09, 300)
        self.track = TrackRecordSource(
            scalar_18=1.25,
            min_x=3,
            min_y=4,
            max_x=7,
            max_y=9,
            component_point_count=11,
            source_identifier_32=0x1234,
            output_age_34=2,
            group_identifier_37=5,
            fallback_profile_flag_43=1,
        )
        self.context = OutputRecordContext(
            x_node_count=68,
            y_node_count=46,
            frame_maximum=100,
            sensor_level=0.07,
            row_remap=tuple(range(46)),
            row_lookup=tuple((value + 10) & 0xFF for value in range(46)),
            profile_predicate=True,
            frame_flag_f49e=False,
        )

    def test_normal_record_fields_and_bytes(self):
        record = build_output_record(
            self.policy,
            self.track,
            SelectedPosition(6.25, 8.25, 1),
            self.context,
            track_index=7,
            sensor_index=2,
            byte_34=9,
            byte_35=10,
        )
        self.assertEqual(record.record_type, 1)
        self.assertEqual((record.min_x, record.min_y), (3, 4))
        self.assertEqual((record.max_x, record.max_y), (7, 9))
        self.assertEqual(record.mapped_row, 18)
        self.assertTrue(record.level_passed)  # strict 0.06 < 0.07
        raw = record.to_bytes()
        self.assertEqual(len(raw), 0x38)
        self.assertEqual(struct.unpack_from("<ff", raw, 0), (6.25, 8.25))
        self.assertEqual(struct.unpack_from("<f", raw, 0x10)[0], 1.25)
        self.assertEqual(struct.unpack_from("<I", raw, 0x14)[0], 2)
        self.assertEqual(struct.unpack_from("<6H", raw, 0x18), (3, 4, 7, 9, 11, 1))
        self.assertEqual(struct.unpack_from("<H", raw, 0x24)[0], 0x1234)
        self.assertEqual(raw[0x26:0x2F], bytes((1, 5, 5, 1, 18, 0, 0, 1, 0)))
        self.assertEqual(struct.unpack_from("<i", raw, 0x30)[0], 7)
        self.assertEqual(raw[0x34:0x38], bytes((9, 10, 1, 0)))

    def test_extracts_threshold_policy_from_project_blob(self):
        blob = bytearray(0x2000)
        blob[0:4] = b"PSDB"
        struct.pack_into("<HHI", blob, 4, 4, 0x0C83, 0)
        struct.pack_into("<I", blob, 0x18, len(blob))
        config = PROJECT_CONFIG_OFFSET
        struct.pack_into("<f", blob, config + 0x0C, 0.055)
        struct.pack_into("<ffH", blob, config + 0xE6C, 0.09, 0.08, 50)
        policy = OutputThresholdPolicy.from_dll(bytes(blob), 0x0C83)
        self.assertEqual(policy.recent_signal_baseline, 0.054999999701976776)
        self.assertEqual(policy.ordinary_level_threshold, 0.09000000357627869)
        self.assertEqual(policy.frame_flag_level_threshold, 0.07999999821186066)
        self.assertEqual(policy.frame_level_gate, 50)

    def test_serialization_preserves_bytes_the_dll_does_not_write(self):
        record = build_output_record(
            self.policy,
            self.track,
            SelectedPosition(6.25, 8.25, 1),
            self.context,
            track_index=7,
            sensor_index=2,
        )
        base = bytes(range(0x38))
        raw = record.to_bytes(base)
        for offset in (*range(0x08, 0x10), 0x2B, 0x2F, 0x37):
            self.assertEqual(raw[offset], base[offset])
        with self.assertRaisesRegex(ValueError, "exactly 0x38"):
            record.to_bytes(b"short")

    def test_outer_frame_header_and_caller_owned_bytes(self):
        record = build_output_record(
            self.policy,
            self.track,
            SelectedPosition(6.25, 8.25, 1),
            self.context,
            track_index=7,
            sensor_index=2,
        )
        base = bytes((index * 3) & 0xFF for index in range(4 + 0x38))
        raw = serialize_output_frame(
            (record,),
            global_context_active=True,
            retained_state2_count=2,
            base=base,
        )
        self.assertEqual(raw[:3], b"\x01\x01\x02")
        self.assertEqual(raw[3], base[3])
        self.assertEqual(raw[4 + 0x2B], base[4 + 0x2B])
        self.assertEqual(struct.unpack_from("<i", raw, 4 + 0x30)[0], 7)

        with self.assertRaisesRegex(ValueError, "more than 34"):
            serialize_output_frame(
                (record,) * 35,
                global_context_active=False,
                retained_state2_count=0,
            )

    def test_split_record_builds_clipped_one_cell_bounds(self):
        record = build_output_record(
            self.policy,
            self.track,
            SelectedPosition(67.0, 0.0, 2),
            self.context,
            track_index=4,
            sensor_index=0,
            split_flag=3,
        )
        self.assertEqual(record.record_type, 3)
        self.assertEqual(record.scalar_10, 4.5)
        self.assertEqual((record.min_x, record.max_x), (66, 67))
        self.assertEqual((record.min_y, record.max_y), (0, 1))

    def test_threshold_ordering_and_strict_comparison(self):
        position = SelectedPosition(1.0, 1.0, 2)
        at_other_profile_threshold = OutputRecordContext(
            **{**self.context.__dict__, "sensor_level": 0.07500000298023224}
        )
        record = build_output_record(
            self.policy,
            self.track,
            position,
            at_other_profile_threshold,
            track_index=0,
            sensor_index=0,
        )
        self.assertFalse(record.level_passed)

        frame_flag_context = OutputRecordContext(
            **{
                **self.context.__dict__,
                "profile_predicate": False,
                "frame_flag_f49e": True,
                "sensor_level": 0.10,
            }
        )
        record = build_output_record(
            self.policy,
            self.track,
            position,
            frame_flag_context,
            track_index=0,
            sensor_index=0,
        )
        self.assertTrue(record.level_passed)  # project +e70 (0.09)

        large_frame = OutputRecordContext(
            **{
                **frame_flag_context.__dict__,
                "frame_maximum": 301,
                "sensor_level": 0.11,
            }
        )
        record = build_output_record(
            self.policy,
            self.track,
            position,
            large_frame,
            track_index=0,
            sensor_index=0,
        )
        self.assertFalse(record.level_passed)  # falls back to +e6c (0.12)

    def test_old_record_uses_project_recent_signal_baseline(self):
        old_track = TrackRecordSource(**{**self.track.__dict__, "output_age_34": 4})
        low_context = OutputRecordContext(
            **{**self.context.__dict__, "sensor_level": 0.055}
        )
        record = build_output_record(
            self.policy,
            old_track,
            SelectedPosition(2.0, 2.0, 0),
            low_context,
            track_index=0,
            sensor_index=0,
        )
        self.assertFalse(record.recent_or_high_signal)


if __name__ == "__main__":
    unittest.main()
