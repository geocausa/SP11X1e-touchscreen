# SPDX-License-Identifier: GPL-2.0
"""Synthetic parser safety cases; these are not pen receiver acceptance."""
import struct
import unittest

from tools.inspect_pen_ccp import HEAT_REPORT_IDS, inspect_report, parse_vendor


def record(kind, data=b"", flags=0):
    return struct.pack("<BBH", kind, flags, len(data)) + data


def report(vendor, rid=0x12):
    section = struct.pack("<IHB", len(vendor) + 7, 0xFF00, 0) + vendor
    return bytes([rid]) + struct.pack("<HIHB", 42, len(section) + 7, 0, 0) + section


class PenCcpTests(unittest.TestCase):
    def test_general_and_detection_offsets_are_payload_relative(self):
        general = struct.pack("<IIHBB", 1234, 5678, 6, 9, 10) + bytes(52)
        detection = bytes(12) + bytes((2, 3, 6, 0))
        records = parse_vendor(record(0x57, general) + record(0x62, detection))
        self.assertEqual(records[0].fields, dict(frame=1234, timestamp=5678, cycle=6, lf_gain=9, hf_gain=10))
        self.assertEqual(records[1].fields, dict(chip=2, window=3, window_type=6))

    def test_unknown_records_preserve_flags_and_size(self):
        records = parse_vendor(record(0x95, b"abc", flags=19) + record(0x63, b"\x07"))
        self.assertEqual((records[0].name, records[0].flags, records[0].size), ("unknown", 19, 3))
        self.assertEqual(records[1].offset, 7)
        self.assertEqual(records[1].fields, {"reason": 7})

    def test_all_heat_report_ids_and_seven_byte_sections(self):
        for rid in HEAT_REPORT_IDS:
            result = inspect_report(report(b"", rid))
            self.assertEqual(result["sections"][0]["records"], [])
            self.assertEqual(result["scan_time"], 42)
            self.assertFalse(result["pen_receiver_implemented"])

    def test_padding_and_zero_terminator(self):
        self.assertEqual(parse_vendor(b"\xff"), [])
        self.assertEqual(parse_vendor(b"\x00\x37\x00\x00garbage"), [])
        self.assertEqual(len(parse_vendor(record(0x5B, b"abcd") + b"\xff")), 1)

    def test_rejects_truncated_header_or_payload(self):
        for data in (b"\x57", b"\x57\x00\x40", b"\x57\x00\x40\x00" + bytes(63)):
            with self.assertRaises(ValueError):
                parse_vendor(data)

    def test_rejects_unsupported_known_lengths(self):
        for kind, payload in ((0x57, bytes(63)), (0x62, bytes(15)), (0x63, b"")):
            with self.assertRaises(ValueError):
                parse_vendor(record(kind, payload))

    def test_record_count_bound(self):
        item = record(0x5B)
        self.assertEqual(len(parse_vendor(item * 100 + b"\xff")), 100)
        with self.assertRaisesRegex(ValueError, "100"):
            parse_vendor(item * 101)

    def test_byte_bound(self):
        with self.assertRaises(ValueError):
            parse_vendor(bytes(8193))
        with self.assertRaises(ValueError):
            inspect_report(bytes(8193))

    def test_report_trailing_bytes_are_not_ccp(self):
        result = inspect_report(report(record(0x63, b"\x03")) + b"\x57\x00\x40\x00")
        self.assertEqual(result["trailing_bytes"], 4)
        self.assertEqual(len(result["sections"][0]["records"]), 1)

    def test_container_and_section_boundaries(self):
        valid = report(record(0x5C, b"1234"))
        for end in range(len(valid)):
            with self.assertRaises(ValueError):
                inspect_report(valid[:end])
        for offset, value in ((3, 6), (3, 0xFFFFFFFF), (10, 6), (10, 999)):
            malformed = bytearray(valid)
            struct.pack_into("<I", malformed, offset, value)
            with self.assertRaises(ValueError):
                inspect_report(bytes(malformed))

    def test_unsupported_envelopes(self):
        for offset, value in ((0, 1), (7, 1), (9, 1)):
            malformed = bytearray(report(b""))
            malformed[offset] = value
            with self.assertRaises(ValueError):
                inspect_report(bytes(malformed))

    def test_pen_metadata_is_not_position_or_pressure(self):
        parsed = parse_vendor(record(0x5B, bytes(24)) + record(0x5C, bytes(32)))
        self.assertEqual([r.name for r in parsed], ["pen_magnitude", "pen_dft"])
        self.assertEqual([r.fields for r in parsed], [{}, {}])
