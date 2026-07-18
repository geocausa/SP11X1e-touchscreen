# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

from pathlib import Path
import re
import struct
import unittest

from tools.decode_heat_frame import (
    ContextMetadataState,
    HeatCalibrationPolicy,
    GRID_COLS,
    GRID_ROWS,
    GRID_SAMPLES,
    HEAT_THRESHOLD,
    MIN_CONTACT_PIXELS,
    WINDOWS_SIGNAL_ZERO,
    WINDOWS_NSR_CUTOFF,
    WINDOWS_NSR_ROW_TO_BIN,
    WINDOWS_STRONG_MAX,
    accepted_contacts,
    connected_components,
    extract_heatmap,
    extract_context_sources,
    extract_nsr_bins,
    extract_report,
    local_peak_counts,
    modal_baseline,
    parse_sections,
    parse_metadata_records,
    phase76_output_centroid,
    halo_ratio,
    secondary_detector_features,
    windows_classifier_features,
    windows_signal,
)
from tools.track_heat_contacts import (
    TRACK_CONFIRM_NORMAL,
    TRACK_CONFIRM_SPLIT,
    TRACK_CONFIRM_WEAK,
    TRACK_SPLIT_RADIUS,
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


def make_metadata_section(nsr_bins):
    payload = bytes([len(nsr_bins), 0, 0, 0]) + b"".join(
        struct.pack("<Hxx", value) for value in nsr_bins
    )
    records = (
        struct.pack("<BBH", 0x00, 0x04, 0)
        + struct.pack("<BBH", 0x04, 0x04, len(payload))
        + payload
    )
    length = 7 + len(records)
    return struct.pack("<IHBB", length, 0xFF00, 0, records[0]) + records[1:]


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

    def test_extracts_optional_u16_calibration_and_preserves_fmadd_path(self):
        blob = bytearray(0x1000)
        blob[0:4] = b"PSDB"
        struct.pack_into("<HH", blob, 4, 4, 0x0C83)
        struct.pack_into("<I", blob, 0x18, len(blob))
        struct.pack_into("<ff", blob, 0x798, 0.5, 2.25)
        blob[0x7A0] = 1
        policy = HeatCalibrationPolicy.from_dll(bytes(blob), 0x0C83)
        self.assertEqual(policy, HeatCalibrationPolicy(True, 0.5, 2.25))
        self.assertEqual(policy.convert_u16(3), 3)
        self.assertEqual(policy.convert_u16(0xFFFF), 0xFF)

        blob[0x7A0] = 0
        disabled = HeatCalibrationPolicy.from_dll(bytes(blob), 0x0C83)
        with self.assertRaisesRegex(ValueError, "disabled"):
            disabled.convert_u16(3)

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

    def test_metadata_type04_nsr_bins(self):
        values = tuple(range(16))
        section = parse_sections(self._report_with_section(make_metadata_section(values)))[2][0]
        records = parse_metadata_records(section)
        self.assertEqual([record.kind for record in records], [0x00, 0x04])
        self.assertEqual(extract_nsr_bins(section), values)

    def test_metadata_rejects_truncated_type04(self):
        payload = b"\x02\x00\x00\x00\x01\x00\x00\x00"
        records = struct.pack("<BBH", 0x04, 0x04, len(payload)) + payload
        section = struct.pack("<IHBB", 7 + len(records), 0xFF00, 0, records[0]) + records[1:]
        parsed = parse_sections(self._report_with_section(section))[2][0]
        with self.assertRaisesRegex(ValueError, "truncated"):
            extract_nsr_bins(parsed)

    def test_metadata_context_sources_and_persistent_type94_state(self):
        records = (
            struct.pack("<BBH", 0x07, 0x04, 4)
            + bytes.fromhex("12 34 56 78")
            + struct.pack("<BBH", 0x94, 0, 10)
            + bytes.fromhex("02 01 11 22 33 44 55 66 00 a5")
        )
        section = struct.pack("<IHBB", 7 + len(records), 0xFF00, 0, records[0]) + records[1:]
        parsed = parse_sections(self._report_with_section(section))[2][0]
        sources = extract_context_sources(parsed)
        self.assertEqual((sources.frame_b771, sources.frame_b7ea), (0x34, 0xA5))
        self.assertEqual(sources.next_state, ContextMetadataState(0xA5))

        type07_only = struct.pack("<BBH", 0x07, 0x04, 4) + b"\x00\x00\x00\x00"
        section = (
            struct.pack("<IHBB", 7 + len(type07_only), 0xFF00, 0, type07_only[0])
            + type07_only[1:]
        )
        parsed = parse_sections(self._report_with_section(section))[2][0]
        persisted = extract_context_sources(parsed, sources.next_state)
        self.assertEqual((persisted.frame_b771, persisted.frame_b7ea), (0, 0xA5))

    def test_metadata_context_malformed_records_do_not_invent_values(self):
        malformed_type07 = struct.pack("<BBH", 0x07, 0x04, 3) + b"\x01\x02\x03"
        section = (
            struct.pack(
                "<IHBB", 7 + len(malformed_type07), 0xFF00, 0, malformed_type07[0]
            )
            + malformed_type07[1:]
        )
        parsed = parse_sections(self._report_with_section(section))[2][0]
        sources = extract_context_sources(
            parsed, ContextMetadataState(7), initial_type07_payload1=9
        )
        self.assertEqual((sources.frame_b771, sources.frame_b7ea), (9, 7))

        bad_type94 = struct.pack("<BBH", 0x94, 0, 2) + b"\x01\x00"
        section = (
            struct.pack("<IHBB", 7 + len(bad_type94), 0xFF00, 0, bad_type94[0])
            + bad_type94[1:]
        )
        parsed = parse_sections(self._report_with_section(section))[2][0]
        with self.assertRaisesRegex(ValueError, "subtype 0 is truncated"):
            extract_context_sources(parsed)

    def test_windows_nsr_cutoff_is_strict_and_row_mapped(self):
        grid = make_grid([(16, 12, 0x80), (16, 13, 0x80), (17, 12, 0x80)])
        sensor_row = 16
        selected_bin = WINDOWS_NSR_ROW_TO_BIN[sensor_row]
        bins = [0] * 16
        bins[selected_bin] = WINDOWS_NSR_CUTOFF
        accepted, _ = accepted_contacts(grid, 0xB5, nsr_bins=tuple(bins))
        self.assertEqual(len(accepted), 1)
        bins[selected_bin] += 1
        rejected, _ = accepted_contacts(grid, 0xB5, nsr_bins=tuple(bins))
        self.assertEqual(rejected, [])

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

    def test_phase76_centroid_uses_project_normal_baseline(self):
        grid = make_grid(
            [
                (10, 20, 150),
                (10, 21, 170),
                (11, 20, 165),
            ]
        )
        component = connected_components(grid, 0xB5)[0]
        output = phase76_output_centroid(grid, component)

        weights = (21, 1, 6)
        expected_x = (20 * weights[0] + 21 * weights[1] + 20 * weights[2])
        expected_y = (10 * weights[0] + 10 * weights[1] + 11 * weights[2])
        total = sum(weights)
        self.assertEqual(
            output,
            (
                expected_x * 32767 // (total * (GRID_COLS - 1)),
                expected_y * 32767 // (total * (GRID_ROWS - 1)),
            ),
        )

    def test_windows_detector_uses_four_connectivity(self):
        grid = make_grid([(10, 10, 0x80), (11, 11, 0x80)])
        contacts, palms = accepted_contacts(grid, 0xB5)
        self.assertEqual(len(contacts), 2)
        self.assertEqual(palms, 0)

    def test_windows_covariance_geometry_distinguishes_elongation(self):
        square = make_grid(
            [(10, 10, 0x80), (10, 11, 0x80), (11, 10, 0x80), (11, 11, 0x80)]
        )
        line = make_grid([(20, column, 0x80) for column in range(20, 24)])
        square_shape = connected_components(square, 0xB5)[0]
        line_shape = connected_components(line, 0xB5)[0]

        self.assertAlmostEqual(square_shape["axis_ratio"], 1.0)
        self.assertGreater(line_shape["axis_ratio"], square_shape["axis_ratio"])
        self.assertGreaterEqual(square_shape["major_axis"], 1.0)
        self.assertGreaterEqual(square_shape["minor_axis"], 1.0)

    def test_windows_one_pixel_spread_uses_degenerate_default(self):
        component = connected_components(make_grid([(10, 10, 0x80)]), 0xB5)[0]
        self.assertEqual(component["axis_ratio"], 1.0)
        self.assertEqual(component["normalized_spread"], 1.0)

    def test_windows_secondary_detector_uses_peak_relative_reruns(self):
        values = [80, 100, 120, 140, 160]
        grid = make_grid(
            [(10, 10 + index, value) for index, value in enumerate(values)],
            baseline=180,
        )
        component = connected_components(grid, 180)[0]
        self.assertEqual(
            secondary_detector_features(grid, component),
            (1, 3, 1, 2, 1, 1),
        )
        features = windows_classifier_features(grid, component)
        self.assertEqual(features[:7], (5.0, 3.0, 2.0, 1.0, 1.0, 1.0, 1.0))

    def test_windows_weak_candidate_keeps_default_rerun_features(self):
        grid = make_grid(
            [(20, 20, 150), (20, 21, 155), (20, 22, 160)], baseline=180
        )
        component = connected_components(grid, 180)[0]
        self.assertLess(windows_signal(150), 0.07)
        self.assertEqual(
            secondary_detector_features(grid, component),
            (1, 3, 1, 3, 1, 3),
        )

    def test_windows_local_peak_producer_counts_single_and_plateau_peaks(self):
        single = make_grid(
            [(10, 10, 120), (10, 11, 140), (11, 10, 140)], baseline=180
        )
        component = connected_components(single, 180)[0]
        self.assertEqual(local_peak_counts(single, component), (1, 1))

        plateau = make_grid(
            [(20, 20, 120), (20, 21, 120), (20, 22, 150)], baseline=180
        )
        component = connected_components(plateau, 180)[0]
        # The lower row-major index wins the exact-signal tie.
        self.assertEqual(local_peak_counts(plateau, component), (1, 1))

    def test_windows_local_peak_floor_is_strict(self):
        weak = make_grid(
            [(30, 30, 163), (30, 31, 170), (31, 30, 170)], baseline=180
        )
        component = connected_components(weak, 180)[0]
        self.assertEqual(local_peak_counts(weak, component), (1, 0))

    def test_windows_halo_walk_accumulates_falling_outer_energy(self):
        values = [80, 100, 120, 140, 160]
        grid = make_grid(
            [(10, 10 + index, value) for index, value in enumerate(values)],
            baseline=172,
        )
        component = connected_components(grid, 172)[0]
        self.assertAlmostEqual(halo_ratio(grid, component), 0.40695479884208435)

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
            Path(__file__).parents[1] / "phase55/modules/mshw0485_touch.c"
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
            "G6TS_NSR_BINS": 16,
            "G6TS_NSR_CUTOFF": WINDOWS_NSR_CUTOFF,
            "G6TS_MAX_CONTACTS": 10,
            "G6TS_TRACK_MATCH_MAX": 4096,
            "G6TS_CONTACT_HOLD_FRAMES": 6,
            "G6TS_TRACK_CONFIRM_NORMAL": TRACK_CONFIRM_NORMAL,
            "G6TS_TRACK_CONFIRM_WEAK": TRACK_CONFIRM_WEAK,
            "G6TS_TRACK_CONFIRM_SPLIT": TRACK_CONFIRM_SPLIT,
            "G6TS_TRACK_SPLIT_RADIUS": TRACK_SPLIT_RADIUS,
            "G6TS_SMOOTH_STATIONARY_MAX": 64,
            "G6TS_SMOOTH_SLOW_MAX": 256,
        }
        for name, value in expected.items():
            match = re.search(rf"^#define {name}\s+(\d+)U$", source, re.MULTILINE)
            self.assertIsNotNone(match, name)
            self.assertEqual(int(match.group(1)), value, name)

        mapping = re.search(
            r"g6ts_nsr_row_to_bin\[G6TS_HEAT_ROWS\]\s*=\s*\{([^}]*)\}",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(mapping)
        kernel_mapping = tuple(int(value) for value in re.findall(r"\d+", mapping.group(1)))
        self.assertEqual(kernel_mapping, WINDOWS_NSR_ROW_TO_BIN)

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
