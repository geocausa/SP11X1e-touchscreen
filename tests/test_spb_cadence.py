# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "analyze_spb_cadence", ROOT / "tools" / "analyze_spb_cadence.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def response_events(start, body):
    words = len(body) // 4
    header = bytes((0x03, words & 0xFF, words >> 8, 0x5A))
    return [
        (1, "tx", start, MODULE.HEADER_COMMAND),
        (2, "rx", start + 10, header),
        (3, "tx", start + 5010, MODULE.BODY_COMMAND),
        (4, "rx", start + 5020, body),
    ]


class SpbCadenceTests(unittest.TestCase):
    def test_pairs_complete_heat_responses_and_reports_microseconds(self):
        body = bytes((1, 0, 0, 0x12))
        events = response_events(1000, body) + response_events(33020, body)
        responses = MODULE.pair_responses(events)
        heat, header_body, body_header = MODULE.heat_cadence_us(responses)
        self.assertEqual(len(heat), 2)
        self.assertEqual(header_body, [500.0, 500.0])
        self.assertEqual(body_header, [2700.0])

    def test_rejects_malformed_header_and_length(self):
        body = bytes((1, 0, 0, 0x12))
        malformed = response_events(1000, body)
        malformed[1] = (2, "rx", 1010, bytes((3, 2, 0, 0)))
        self.assertEqual(MODULE.pair_responses(malformed), [])

    def test_summary_uses_stable_nearest_rank_fields(self):
        summary = MODULE.summarize([4.0, 1.0, 3.0, 2.0])
        self.assertEqual(summary["count"], 4)
        self.assertEqual(summary["min"], 1.0)
        self.assertEqual(summary["median"], 2.5)
        self.assertEqual(summary["max"], 4.0)


if __name__ == "__main__":
    unittest.main()
