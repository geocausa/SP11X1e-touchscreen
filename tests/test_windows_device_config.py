# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import unittest

from tools.windows_device_config import (
    build_report56,
    report56_identity_from_report60,
)


class WindowsDeviceConfigTests(unittest.TestCase):
    def setUp(self):
        self.report60 = bytes.fromhex(
            "01 00 00 04 89 14 00 3f 40 12 75 00 28 6a 04 80 "
            "00 00 00 00 bc 00 00 00 e6 00 00 00 4a 00 00 00 "
            "2e 00 00 00 86 00 00 00 78 00 00 00 00 00 00 00 "
            "00 00 00 00 00 00 00 00 28 30 03 80"
        )

    def test_report60_mirrors_captured_report56_identity(self):
        identity = report56_identity_from_report60(self.report60)
        self.assertEqual(identity, bytes.fromhex("bc e6 4a 2e 86 78"))
        self.assertEqual(
            build_report56(identity, 0),
            bytes.fromhex("bc e6 4a 2e 86 78 00"),
        )

    def test_lengths_and_boolean_are_strict(self):
        with self.assertRaises(ValueError):
            report56_identity_from_report60(self.report60[:-1])
        with self.assertRaises(ValueError):
            build_report56(b"12345", 0)
        with self.assertRaises(ValueError):
            build_report56(b"123456", 2)


if __name__ == "__main__":
    unittest.main()
