# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import unittest

from tools.extract_kdnet_hidspi import parse_transfers


def mst_block(tx: bytes, rx_len: int = 0) -> str:
    dump = " ".join(f"{byte:02x}" for byte in tx)
    return f"""[MST-entry]
System Uptime: 0 days 0:00:01.234
x1=0000000000000002 x2=0000000000000004 x3=0000000000000000 x4=ffffbc83`a67b29e0 x5={len(tx):016x} x6=0000000000000000 x7={rx_len:016x}
ffffbc83`a67b29e0  {dump}  rendered-ascii
 # Child-SP          RetAddr               Call Site
"""


class KdnetHidspiTests(unittest.TestCase):
    def test_declared_content_is_separate_from_rounded_padding(self):
        wire = bytes.fromhex("e2 00 20 00 03 01 00 70 01 a5 00 02")
        transfer = next(parse_transfers(mst_block(wire)))
        self.assertEqual(transfer.tx_len, 12)
        self.assertEqual(transfer.content_len, 1)
        self.assertEqual(transfer.content, b"\x01")
        self.assertEqual(transfer.padding, bytes.fromhex("a5 00 02"))

    def test_full_report09_has_63_content_bytes_and_one_pad_byte(self):
        content = bytes([0x8E, 0xA1, 0x01]) + bytes(60)
        wire = bytes.fromhex("e2 00 20 00 05 3f 00 09") + content + b"\x00"
        transfer = next(parse_transfers(mst_block(wire)))
        self.assertEqual(transfer.tx_len, 72)
        self.assertEqual(transfer.content_id, 0x09)
        self.assertEqual(transfer.content, content)
        self.assertEqual(transfer.padding, b"\x00")

    def test_parser_never_reads_past_x5(self):
        wire = bytes.fromhex("e2 00 20 00 03 01 00 05 01 a5 00 02")
        log = mst_block(wire).replace("rendered-ascii", "de ad be ef rendered-ascii")
        transfer = next(parse_transfers(log))
        self.assertEqual(transfer.tx, wire)
        self.assertNotIn(bytes.fromhex("de ad be ef"), transfer.tx)

    def test_legacy_mode_setup_dump_is_also_length_bounded(self):
        log = """[MODE-SETUP] type=03 id=70 txLen=c rxLen=0
ffff9a85`2c68b660  e2 00 20 00 03 01 00 70-01 a5 00 02 00 00 00 00
ffff9a85`2c68b670  de ad be ef 00 00 00 00-00 00 00 00 00 00 00 00
next event
"""
        transfer = next(parse_transfers(log))
        self.assertEqual(transfer.tx_len, 12)
        self.assertEqual(transfer.content, b"\x01")
        self.assertEqual(transfer.padding, bytes.fromhex("a5 00 02"))
        self.assertNotIn(bytes.fromhex("de ad be ef"), transfer.tx)


if __name__ == "__main__":
    unittest.main()
