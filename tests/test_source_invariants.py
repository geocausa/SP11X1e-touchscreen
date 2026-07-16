# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "phase55" / "modules" / "g6ts_biosref.c"


def function_body(source: str, name: str) -> str:
    start = source.index(name)
    opening = source.index("{", start)
    depth = 0
    for offset in range(opening, len(source)):
        if source[offset] == "{":
            depth += 1
        elif source[offset] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : offset + 1]
    raise AssertionError(f"unterminated function {name}")


class SourceInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CLIENT.read_text(encoding="utf-8")

    def test_recovery_uses_hardware_validated_minimal_order(self):
        body = function_body(self.source, "g6ts_full_reinitialize_locked")
        ordered = (
            "g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x05",
            "g6ts_dma_feature_exchange(ts, GET_FEATURE, 0x70",
            "g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x70",
            "g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x56",
        )
        positions = [body.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_windows_collection_setup_is_not_replayed_during_recovery(self):
        body = function_body(self.source, "g6ts_full_reinitialize_locked")
        forbidden = (
            "GET_FEATURE, 0x60",
            "OUTPUT_REPORT, 0x65",
            "GET_FEATURE, 0x06",
            "OUTPUT_REPORT, 0x09",
            "GET_FEATURE, 0x73",
        )
        for command in forbidden:
            self.assertNotIn(command, body)

        for removed_symbol in (
            "g6ts_output65",
            "g6ts_output09_a1_template",
            "g6ts_output09_a5_template",
            "g6ts_etw_firmware_version",
        ):
            self.assertNotIn(removed_symbol, self.source)

    def test_assignment_initializes_every_output_slot(self):
        body = function_body(self.source, "g6ts_assign_tracks")
        initialization = body.index("contact_slots[i] = -1")
        early_return = body.index("if (!active_count || !count)")
        self.assertLess(initialization, early_return)


if __name__ == "__main__":
    unittest.main()
