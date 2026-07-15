# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

from pathlib import Path
import re
import struct
import unittest

from tools.decode_heat_frame import (
    GRID_COLS,
    GRID_ROWS,
    GRID_SAMPLES,
    HEAT_THRESHOLD,
    MIN_CONTACT_PIXELS,
    WINDOWS_SIGNAL_ZERO,
    WINDOWS_STRONG_MAX,
    accepted_contacts,
    extract_heatmap,
    extract_report,
    modal_baseline,
    parse_sections,
)


def make_grid(points=(), baseline=0xB5):
    grid = bytearray([baseline] * GRID_SAMPLES)
    for row, col, value in points:
        grid[row * GRID_COLS + col] = value
    return bytes(grid)


def make_section(blocks, kind=0x0100, mode=1, header_value=8):
    payload = b"".join(
        struct.pack("<II", destination, len(data)) + data
        for destination, data in blocks
    )
    length = 8 + len(payload)
    return struct.pack("<IHBB", length, kind, mode, header_value) + payload


def make_report(grid, trailer=b""):
    section = make_section([(0, grid)])
    container_length = 7 + len(section)
    return (
        b"\x12"
        + struct.pack("<H", 0x1234)
        + struct.pack("<I", container_length)
        + b"\x00\x00\x00"
        + section
        + trailer
    )


class HeatDecoderTests(unittest.TestCase):
    def test_raw_and_class1_report_envelopes(self):
        report = make_report(make_grid())
        self.assertEqual(extract_report(report), report)
        self.assertEqual(extract_report(b"\x01\x00\x00" + report), report)
        with self.assertRaisesRegex(ValueError, "not a report-0x12"):
            extract_report(b"\x11\x00\x00")

    def test_parse_and_reassemble_full_grid(self):
        grid = make_grid([(5, 7, 0x80)])
        report = make_report(grid, trailer=b"metadata")
        scan_time, _, sections, trailer = parse_sections(report)
        self.assertEqual(scan_time, 0x1234)
        self.assertEqual(len(sections), 1)
        self.assertEqual(extract_heatmap(sections[0]), grid)
        self.assertEqual(trailer, b"metadata")

    def test_overlap_and_incomplete_grid_are_rejected(self):
        overlap = make_section([(0, b"\xb5" * 10), (5, b"\xb5" * 10)])
        with self.assertRaisesRegex(ValueError, "overlaps prior data"):
            extract_heatmap(parse_sections(self._report_with_section(overlap))[2][0])

        incomplete = make_section([(0, b"\xb5" * (GRID_SAMPLES - 1))])
        with self.assertRaisesRegex(ValueError, "leaves 1 grid samples"):
            extract_heatmap(parse_sections(self._report_with_section(incomplete))[2][0])

    def test_modal_baseline_uses_kernel_tie_break(self):
        baseline, count = modal_baseline(bytes([0xB5, 0xB4, 0xB5, 0xB4]))
        self.assertEqual((baseline, count), (0xB4, 2))

    def test_two_finger_components(self):
        grid = make_grid(
            [
                (5, 5, 0x90),
                (5, 6, 0x91),
                (30, 50, 0x80),
                (31, 50, 0x82),
            ]
        )
        contacts, palms = accepted_contacts(grid, 0xB5)
        self.assertEqual(len(contacts), 2)
        self.assertEqual(palms, 0)
        self.assertGreater(contacts[0]["strength"], contacts[1]["strength"])

    def test_windows_detector_uses_four_connectivity(self):
        grid = make_grid([(10, 10, 0x80), (11, 11, 0x80)])
        contacts, palms = accepted_contacts(grid, 0xB5)
        self.assertEqual(len(contacts), 2)
        self.assertEqual(palms, 0)

    def test_strong_two_cell_candidate_survives(self):
        strong, _ = accepted_contacts(
            make_grid([(10, 10, WINDOWS_STRONG_MAX), (10, 11, WINDOWS_STRONG_MAX)]),
            0xB5,
        )
        weak, _ = accepted_contacts(
            make_grid(
                [
                    (10, 10, WINDOWS_STRONG_MAX + 1),
                    (10, 11, WINDOWS_STRONG_MAX + 1),
                ]
            ),
            0xB5,
        )
        self.assertEqual(len(strong), 1)
        self.assertEqual(weak, [])

    def test_broad_component_is_rejected_as_palm(self):
        points = [(20, column, 0x80) for column in range(13)]
        contacts, palms = accepted_contacts(make_grid(points), 0xB5)
        self.assertEqual(contacts, [])
        self.assertEqual(palms, 1)

    def test_contact_limit_keeps_ten_strongest(self):
        points = []
        for index in range(11):
            row = 2 + (index // 4) * 12
            col = 2 + (index % 4) * 16
            value = 0x80 + index
            points.extend([(row, col, value), (row, col + 1, value)])
        contacts, palms = accepted_contacts(make_grid(points), 0xB5)
        self.assertEqual(len(contacts), 10)
        self.assertEqual(palms, 0)
        strengths = [contact["strength"] for contact in contacts]
        self.assertEqual(strengths, sorted(strengths, reverse=True))

    def test_python_policy_constants_match_kernel_source(self):
        source = (
            Path(__file__).parents[1] / "phase55/modules/g6ts_biosref.c"
        ).read_text()
        expected = {
            "G6TS_HEAT_ROWS": GRID_ROWS,
            "G6TS_HEAT_COLS": GRID_COLS,
            "G6TS_HEAT_SIGNAL_ZERO": WINDOWS_SIGNAL_ZERO,
            "G6TS_HEAT_THRESHOLD": HEAT_THRESHOLD,
            "G6TS_HEAT_STRONG_MAX": WINDOWS_STRONG_MAX,
            "G6TS_HEAT_MIN_PIXELS": MIN_CONTACT_PIXELS,
            "G6TS_HEAT_PALM_PIXELS": 48,
            "G6TS_HEAT_PALM_SPAN": 12,
            "G6TS_MAX_CONTACTS": 10,
        }
        for name, value in expected.items():
            match = re.search(rf"^#define {name}\s+(\d+)U$", source, re.MULTILINE)
            self.assertIsNotNone(match, name)
            self.assertEqual(int(match.group(1)), value, name)

    @staticmethod
    def _report_with_section(section):
        container_length = 7 + len(section)
        return (
            b"\x12\x00\x00"
            + struct.pack("<I", container_length)
            + b"\x00\x00\x00"
            + section
        )


if __name__ == "__main__":
    unittest.main()
