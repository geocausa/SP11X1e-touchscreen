# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import unittest

from tools.windows_cfu import (
    build_firmware_offer,
    build_info_offer,
    current_version,
    decode_offer_response,
    offered_version,
)


OFFER = bytes.fromhex("00 00 12 00 89 14 00 3f ff ff ff ff 04 04 75 00")
INFO_ACCEPT = bytes.fromhex(
    "00 00 00 a0 00 00 00 00 ff 00 00 00 01 00 00 00"
)
OFFER_REJECT_OLD = bytes.fromhex(
    "00 00 00 a0 00 00 00 00 00 00 00 00 02 00 00 00"
)
REPORT60 = bytes.fromhex(
    "01 00 00 04 89 14 00 3f 40 12 75 00 28 6a 04 80 "
    "00 00 00 00 bc 00 00 00 e6 00 00 00 4a 00 00 00 "
    "2e 00 00 00 86 00 00 00 78 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 28 30 03 80"
)


class WindowsCfuTests(unittest.TestCase):
    def test_information_records_match_capture(self):
        self.assertEqual(
            build_info_offer(0),
            bytes.fromhex("00 00 ff a0") + bytes(12),
        )
        self.assertEqual(build_info_offer(1)[0:4], bytes.fromhex("01 00 ff a0"))
        self.assertEqual(build_info_offer(2)[0:4], bytes.fromhex("02 00 ff a0"))

    def test_installed_offer_becomes_captured_wire_offer(self):
        self.assertEqual(
            build_firmware_offer(OFFER),
            bytes.fromhex(
                "00 00 12 a0 89 14 00 3f ff ff ff ff 04 04 75 00"
            ),
        )

    def test_force_bits_are_explicit_and_off_by_default(self):
        self.assertEqual(build_firmware_offer(OFFER)[1], 0)
        self.assertEqual(build_firmware_offer(OFFER, force_immediate=True)[1], 0x40)
        self.assertEqual(build_firmware_offer(OFFER, force_ignore_version=True)[1], 0x80)

    def test_capture_responses_decode(self):
        info = decode_offer_response(INFO_ACCEPT)
        self.assertEqual((info.token, info.reject_reason, info.status),
                         (0xA0, 0xFF, 1))
        self.assertTrue(info.reserved_words_zero)
        offer = decode_offer_response(OFFER_REJECT_OLD)
        self.assertEqual((offer.token, offer.reject_reason, offer.status),
                         (0xA0, 0, 2))
        self.assertTrue(offer.reserved_words_zero)

    def test_offer_and_inventory_version_match(self):
        self.assertEqual(offered_version(OFFER), 0x3F001489)
        self.assertEqual(current_version(REPORT60), offered_version(OFFER))

    def test_lengths_are_strict(self):
        with self.assertRaises(ValueError):
            build_firmware_offer(bytes(15))
        with self.assertRaises(ValueError):
            decode_offer_response(bytes(15))
        with self.assertRaises(ValueError):
            current_version(bytes(59))


if __name__ == "__main__":
    unittest.main()
