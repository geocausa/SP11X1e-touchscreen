# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

from pathlib import Path
import re
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

    def test_cold_start_matches_complete_etw_order(self):
        body = function_body(self.source, "g6ts_full_reinitialize_locked")
        ordered = (
            "g6ts_dma_report09(ts, false)",
            "g6ts_dma_report09(ts, true)",
            "g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x05",
            "g6ts_dma_feature_exchange(ts, GET_FEATURE, 0x73",
            "g6ts_recovery_read_expected(ts, DATA, G6TS_HEATMAP_REPORT_ID",
        )
        positions = [body.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(body.count("g6ts_dma_report09(ts, false)"), 1)
        self.assertEqual(body.count("g6ts_dma_report09(ts, true)"), 1)

    def test_complete_etw_firmware_and_profile_are_pinned(self):
        self.assertRegex(
            self.source, r"#define G6TS_ETW_PROFILE_LO\s+0x1a\b"
        )
        self.assertRegex(
            self.source, r"#define G6TS_ETW_PROFILE_HI\s+0x03\b"
        )
        version = re.search(
            r"g6ts_etw_firmware_version\[\]\s*=\s*\{([^}]*)\}",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(version)
        self.assertEqual(
            re.findall(r"0x[0-9a-f]+", version.group(1)),
            ["0x89", "0x14", "0x00", "0x3f"],
        )

    def test_assignment_initializes_every_output_slot(self):
        body = function_body(self.source, "g6ts_assign_tracks")
        initialization = body.index("contact_slots[i] = -1")
        early_return = body.index("if (!active_count || !count)")
        self.assertLess(initialization, early_return)


if __name__ == "__main__":
    unittest.main()
