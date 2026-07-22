# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import unittest

from tools.extract_firmware_resources import (
    EXPECTED_TAGS,
    MARKER,
    find_resource_chain,
    parse_resource_chain,
)


def resource(tag: int, data: bytes) -> bytes:
    return bytes([tag]) + MARKER + len(data).to_bytes(4, "little") + data


def chain() -> bytes:
    return b"".join(resource(tag, bytes([tag]) * (index + 1))
                    for index, tag in enumerate(EXPECTED_TAGS))


class FirmwareResourceTests(unittest.TestCase):
    def test_complete_chain_is_found_and_decoded(self):
        image = b"prefix" + chain() + b"suffix"
        records = find_resource_chain(image)
        self.assertEqual([item.tag for item in records], list(EXPECTED_TAGS))
        self.assertEqual(records[0].header_offset, len(b"prefix"))
        self.assertEqual(records[0].data, b"G")
        self.assertEqual(records[-1].data, bytes([0xFF]) * 5)

    def test_bad_marker_is_rejected(self):
        image = bytearray(chain())
        second = 8 + 1
        image[second + 1 : second + 4] = b"bad"
        with self.assertRaisesRegex(ValueError, "bad resource marker"):
            parse_resource_chain(bytes(image), 0)

    def test_truncated_payload_is_rejected(self):
        image = chain()[:-1]
        with self.assertRaisesRegex(ValueError, "declares 5 bytes"):
            parse_resource_chain(image, 0)

    def test_ambiguous_chains_are_rejected(self):
        image = chain() + chain()
        with self.assertRaisesRegex(ValueError, "found 2"):
            find_resource_chain(image)


if __name__ == "__main__":
    unittest.main()
