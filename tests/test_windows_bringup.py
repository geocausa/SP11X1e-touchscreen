# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import unittest

from tools.extract_kdnet_hidspi import Transfer
from tools.extract_windows_bringup import (
    command_owner,
    lifecycle_episodes,
    relevant_events,
)


def write(line: int, report_type: int, content_id: int,
          content: bytes = b"") -> Transfer:
    packet = bytearray(b"\xe2\x00\x20\x00")
    packet.extend((report_type, len(content) & 0xFF, len(content) >> 8, content_id))
    packet.extend(content)
    while len(packet) % 4:
        packet.append(0)
    return Transfer(line, f"t{line}", len(packet), 0, bytes(packet))


def response(line: int, response_class: int, content_id: int,
             content: bytes = b"") -> Transfer:
    body = bytes((response_class, len(content) & 0xFF,
                  len(content) >> 8, content_id)) + content
    return Transfer(
        line,
        f"t{line}",
        8,
        len(body),
        bytes.fromhex("eb 00 10 04 ff ff ff ff"),
        completion_line=line + 1,
        rx=body,
    )


class WindowsBringupTests(unittest.TestCase):
    def test_standard_set_power_off_is_not_vendor_setup(self):
        self.assertEqual(command_owner(7, 1), "power-lifecycle")
        event = relevant_events([write(1, 7, 1, b"\x03")])[0]
        self.assertEqual(event.operation, "COMMAND_CONTENT")
        self.assertEqual(event.owner, "power-lifecycle")
        self.assertEqual(event.content, b"\x03")

    def test_collection_owners_are_not_flattened(self):
        self.assertEqual(command_owner(4, 0x06), "heat-feedback-collection")
        self.assertEqual(command_owner(5, 0x09), "heat-feedback-collection")
        self.assertEqual(command_owner(3, 0x70), "device-config-collection")
        self.assertEqual(command_owner(3, 0x56), "device-config-collection")
        self.assertEqual(command_owner(4, 0x60), "cfu-collection")
        self.assertEqual(command_owner(5, 0x65), "cfu-collection")

    def test_reset_boundaries_distinguish_cold_and_restart(self):
        transfers = [
            response(1, 3, 0),
            write(2, 1, 0),
            response(3, 7, 0, bytes(24)),
            write(4, 2, 0),
            response(5, 8, 0, bytes(1484)),
            response(6, 3, 0),
            write(7, 1, 0),
            response(8, 7, 0, bytes(24)),
            write(9, 3, 0x05, b"\x01"),
        ]
        episodes = lifecycle_episodes(relevant_events(transfers))
        self.assertEqual(len(episodes), 2)
        self.assertEqual(episodes[0].kind, "cold-enumeration")
        self.assertEqual(episodes[1].kind, "restart-or-recovery")

    def test_streaming_data_is_not_misrepresented_as_control(self):
        events = relevant_events([
            response(1, 1, 0x40, b"\x01\x00\x00\x00\x00"),
            response(2, 5, 0x70, b"\x02"),
        ])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].operation, "GET_FEATURE_RESPONSE")

    def test_proven_control_data_responses_are_retained(self):
        events = relevant_events([
            response(1, 1, 0xA0, b"\x01"),
            response(2, 1, 0x65, bytes.fromhex(
                "00 00 00 a0 00 00 00 00 ff 00 00 00 01 00 00 00"
            )),
        ])
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].owner, "heat-feedback-collection")
        self.assertEqual(events[1].owner, "cfu-collection")
        self.assertEqual(events[1].operation, "DATA")


if __name__ == "__main__":
    unittest.main()
