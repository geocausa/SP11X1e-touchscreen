# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import unittest

from tools.extract_cfu_payload import parse_records, unwrap


def record(address: int, data: bytes) -> bytes:
    return address.to_bytes(4, "little") + bytes([len(data)]) + data


class CfuPayloadTests(unittest.TestCase):
    def test_contiguous_records_are_unwrapped(self):
        payload = record(0, b"abc") + record(3, b"defg")
        records = parse_records(payload)
        self.assertEqual([item.file_offset for item in records], [0, 8])
        self.assertEqual(unwrap(payload), b"abcdefg")

    def test_non_contiguous_address_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-contiguous address"):
            unwrap(record(0, b"abc") + record(4, b"def"))

    def test_zero_length_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "zero-length"):
            unwrap(bytes.fromhex("00 00 00 00 00"))

    def test_truncated_data_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "only 2 remain"):
            unwrap(bytes.fromhex("00 00 00 00 04 aa bb"))


if __name__ == "__main__":
    unittest.main()
