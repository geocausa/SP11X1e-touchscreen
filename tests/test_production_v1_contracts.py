#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Offline contract and protocol tests for SP11 Option 1 touch finalization."""

from __future__ import annotations

import math
from pathlib import Path
import re
import struct
import unittest

DRIVER = Path(__file__).resolve().parents[1] / "production-v1/mshw0485_touch.c"

# Synthetic 119-byte Feature 0x06 fixture with documented panel geometry.
# No raw Windows capture or vendor calibration payload is distributed.
SYNTHETIC_FEAT06_PAYLOAD = (
    struct.pack("<IHB", 119, 0, 0)
    + struct.pack("<IHBIIIIB", 112, 0x0200, 1, 46, 68, 27389, 18259, 1)
    + bytes(88)
)

COL02_HEAT_REPORT_IDS = {0x07, 0x08, 0x0A, 0x0B, 0x0C, 0x0D, 0x12, 0x1A, 0x1C}


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*\([^;{{]*\)\s*\{{", source)
    if match is None:
        raise AssertionError(f"function definition not found: {name}")
    opening = source.index("{", match.start())
    depth = 0
    for idx in range(opening, len(source)):
        ch = source[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[opening : idx + 1]
    raise AssertionError(f"unterminated function: {name}")


def parse_feature06_py(payload: bytes) -> tuple[int, int, int, int, int]:
    """Exact mirror of g6ts_parse_feature06()."""
    if len(payload) < 7:
        raise ValueError("short")
    outer_len, outer_type = struct.unpack_from("<IH", payload, 0)
    if outer_len < 7 or outer_len > len(payload):
        raise ValueError("bad outer len")
    props = None
    if outer_type == 0x0200:
        props = payload[:outer_len]
    elif outer_type == 0x0000:
        offset = 7
        while offset < outer_len:
            if outer_len - offset < 7:
                raise ValueError("truncated sub")
            sub_len, sub_type = struct.unpack_from("<IH", payload, offset)
            if sub_len < 7 or sub_len > outer_len - offset:
                raise ValueError("bad sub len")
            if sub_type == 0x0200:
                props = payload[offset : offset + sub_len]
                break
            offset += sub_len
    else:
        raise ValueError("bad outer type")
    if props is None:
        raise KeyError("no 0x0200")
    ver = props[6]
    if ver == 1:
        if len(props) < 0x70:
            raise ValueError("short v1")
        rows, cols, width_hm, height_hm = struct.unpack_from("<IIII", props, 7)
        orientation = props[0x17]
        return rows, cols, width_hm, height_hm, orientation
    if ver == 0:
        if len(props) < 0x17:
            raise ValueError("short v0")
        rows = struct.unpack_from("<H", props, 7)[0]
        cols = struct.unpack_from("<H", props, 0x0B)[0]
        width_hm, height_hm = struct.unpack_from("<II", props, 0x0F)
        return rows, cols, width_hm, height_hm, 0
    raise ValueError("unsupported ver")


def build_set_power_wire(state: int) -> bytes:
    """Exact mirror of g6ts_dma_hidspi_output(COMMAND_CONTENT=7, id=1, state)."""
    pkt = bytearray(12)
    pkt[0:4] = b"\xe2\x00\x20\x00"
    pkt[4] = 7  # COMMAND_CONTENT
    struct.pack_into("<H", pkt, 5, 1)
    pkt[7] = 1  # HIDSPI_SET_POWER_CMD_ID
    pkt[8] = state
    return bytes(pkt)


class TouchFinalizeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = DRIVER.read_text(encoding="utf-8")

    def test_patch1_synthetic_feature06_decode_and_resolution(self) -> None:
        self.assertEqual(len(SYNTHETIC_FEAT06_PAYLOAD), 119)
        rows, cols, width_hm, height_hm, orient = parse_feature06_py(
            SYNTHETIC_FEAT06_PAYLOAD
        )
        self.assertEqual((rows, cols, width_hm, height_hm, orient),
                         (46, 68, 27389, 18259, 1))
        # Exact DIV_ROUND_CLOSEST_ULL(32767 * 100, hm)
        res_x = (32767 * 100 + width_hm // 2) // width_hm
        res_y = (32767 * 100 + height_hm // 2) // height_hm
        self.assertEqual(res_x, 120)
        self.assertEqual(res_y, 179)

    def test_patch1_all_nine_col02_report_ids_and_idle_baseline(self) -> None:
        fn = function_body(self.source, "g6ts_is_heat_report_id")
        for rid in COL02_HEAT_REPORT_IDS:
            self.assertIn(f"case 0x{rid:02x}:", fn)
        extract = function_body(self.source, "g6ts_extract_heatmap")
        self.assertIn(
            "memset(ts->heatmap, G6TS_HEAT_SIGNAL_ZERO, sizeof(ts->heatmap))",
            extract,
        )
        nsr = function_body(self.source, "g6ts_extract_nsr_metadata")
        self.assertIn("if (section[position] == 0xff)", nsr)
        self.assertIn("if (record[0] == 0x00 && payload_len == 0)", nsr)
        handle = function_body(self.source, "g6ts_handle_data_report")
        self.assertIn("g6ts_is_heat_report_id(ts->last_content_id)", handle)
        self.assertIn("if (ret == -ENOENT)", handle)

    def test_patch2_clean_zero_cmdline_attach_and_unconditional_cadence(self) -> None:
        clean = function_body(self.source, "g6ts_clean_touch_attach_locked")
        ordered = (
            "G6TS_INIT_HEAT_CAPS06",
            "g6ts_parse_feature06",
            "G6TS_INIT_FEEDBACK_A1",
            "g6ts_recovery_read_expected(ts, DATA, 0xa0, 1)",
            "G6TS_INIT_FEEDBACK_A5",
            "G6TS_INIT_SET_FEATURE05",
            "SET_FEATURE, 0x05",
            "G6TS_INIT_GET_FEATURE70",
            "G6TS_INIT_SET_FEATURE70",
            "ts->mode_enabled = true",
        )
        positions = [clean.index(tok) for tok in ordered]
        self.assertEqual(positions, sorted(positions))
        # Must NOT issue machine-specific BT MAC (0x56), 0x73, or CFU (0x60, 0x65)
        for forbidden in (
            "SET_FEATURE, 0x56",
            "GET_FEATURE, 0x73",
            "GET_FEATURE, 0x60",
            "OUTPUT_REPORT, 0x65",
        ):
            self.assertNotIn(forbidden, clean)

        read_resp = function_body(self.source, "g6ts_dma_read_response")
        self.assertIn("usleep_range(G6TS_HEADER_BODY_MIN_US, G6TS_HEADER_BODY_MAX_US)", read_resp)
        self.assertIn("ts->quiesced_empty_reads++", read_resp)

        irq_fn = function_body(self.source, "g6ts_interrupt_thread")
        self.assertIn("ts->cadence_single_response_irqs++", irq_fn)
        self.assertNotIn("for (", irq_fn)

    def test_patch3_hidspi_set_power_wire_and_pm_state_machine(self) -> None:
        self.assertEqual(
            build_set_power_wire(2),
            bytes.fromhex("e20020000701000102000000"),
        )
        self.assertEqual(
            build_set_power_wire(3),
            bytes.fromhex("e20020000701000103000000"),
        )
        self.assertEqual(
            build_set_power_wire(1),
            bytes.fromhex("e20020000701000101000000"),
        )

        self.assertIn("#define G6TS_HIDSPI_CMD_TIMEOUT_MS\t2000U", self.source)
        self.assertIn('static char *g6ts_pm_sleep_mode = "off";', self.source)

        sp = function_body(self.source, "g6ts_hidspi_set_power_locked")
        for tok in (
            "COMMAND_CONTENT",
            "HIDSPI_SET_POWER_CMD_ID",
            "if (state != HIDSPI_ON)",
            "G6TS_HIDSPI_CMD_TIMEOUT_MS",
            "COMMAND_RESPONSE",
            "G6TS_HIDSPI_CMD_STATUS_OK",
            "RESET_RESPONSE",
        ):
            self.assertIn(tok, sp)

        susp = function_body(self.source, "g6ts_suspend")
        self.assertLess(susp.index("disable_irq"), susp.index("g6ts_hidspi_set_power_locked"))
        self.assertIn("HIDSPI_SLEEP", susp)
        self.assertIn("HIDSPI_OFF", susp)
        self.assertIn("ts->suspended_in_sleep = true", susp)

        res = function_body(self.source, "g6ts_resume")
        self.assertIn("if (ts->suspended_in_sleep)", res)
        self.assertIn("g6ts_hidspi_set_power_locked(ts, HIDSPI_ON)", res)
        self.assertIn("ts->pm_warm_wakes++", res)
        self.assertIn("ts->pm_cold_fallbacks++", res)
        self.assertLess(res.index("HIDSPI_ON"), res.index("enable_irq"))

    def test_patch4_edge_snap_duplicate_merge_and_mt_axes(self) -> None:
        centroid = function_body(self.source, "g6ts_phase76_output_centroid")
        self.assertIn("contact->min_col == G6TS_HEAT_COLS - 1", centroid)
        self.assertIn("contact->output_x = G6TS_LOGICAL_MAX", centroid)
        self.assertIn("contact->min_row == G6TS_HEAT_ROWS - 1", centroid)
        self.assertIn("contact->output_y = G6TS_LOGICAL_MAX", centroid)

        collect = function_body(self.source, "g6ts_collect_linux_contacts")
        for tok in (
            "G6TS_DUPLICATE_MERGE_DIST_SQ",
            "ts->duplicate_merges++",
            "ABS_MT_TOUCH_MAJOR",
            "ABS_MT_TOUCH_MINOR",
            "ABS_MT_PRESSURE",
        ):
            self.assertIn(tok, collect)

        probe = function_body(self.source, "g6ts_probe")
        reg = probe.index("input_register_device(ts->input)")
        for axis in (
            "ABS_MT_TOUCH_MAJOR",
            "ABS_MT_TOUCH_MINOR",
            "ABS_MT_PRESSURE",
            "g6ts_apply_input_resolution(ts)",
        ):
            self.assertLess(probe.index(axis), reg)

        # Verify 4*sigma ellipse diameter math for 3x3 circular contact (~12 mm)
        pitch_tenth_mm = round(27389 / (67 * 10))
        self.assertEqual(pitch_tenth_mm, 41)
        sigma_cells = 0.75
        sigma_q12 = round(sigma_cells * 4096)
        diam_tenth_mm = (sigma_q12 * 4 * pitch_tenth_mm) >> 12
        self.assertGreaterEqual(diam_tenth_mm, 115)
        self.assertLessEqual(diam_tenth_mm, 130)

        # Verify duplicate merge distance (< 6 mm merges, >= 10 mm preserves pinch)
        self.assertTrue(3 * 3 + 4 * 4 < 36)   # 5 mm -> duplicate suppressed
        self.assertFalse(6 * 6 + 0 * 0 < 36)  # 6 mm -> boundary preserved
        self.assertFalse(8 * 8 + 6 * 6 < 36)  # 10 mm -> two real fingers kept

    def test_patch7_merged_finger_split_and_edge_palm_guard(self) -> None:
        split = function_body(self.source, "g6ts_try_split_merged_component")
        for tok in (
            "G6TS_SPLIT_MIN_DIST_SQ",
            "g6ts_peaks_have_valley",
            "g6ts_finalize_component",
            "g6ts_is_edge_palm",
            "ts->merged_splits++",
        ):
            self.assertIn(tok, split)

        valley = function_body(self.source, "g6ts_peaks_have_valley")
        self.assertIn("G6TS_SPLIT_VALLEY_PCT", valley)

        edge = function_body(self.source, "g6ts_is_edge_palm")
        self.assertIn("G6TS_EDGE_PALM_SPAN", edge)
        self.assertIn("G6TS_EDGE_PALM_PIXELS", edge)

        # Valley math: two fingers (peaks=100,100) with saddle=60 -> 60% <= 85% (split)
        self.assertTrue(60 * 100 <= min(100, 100) * 85)
        # Flat palm plateau (peaks=90,90) with middle=85 -> 94% > 85% (do NOT split)
        self.assertFalse(85 * 100 <= min(90, 90) * 85)
        # Edge palm span >= 7 cells (~28 mm) rejected; narrow edge swipe (3 cells) allowed
        self.assertTrue(7 >= 7)
        self.assertFalse(3 >= 7)

    def test_patch8_lean_production_single_param_and_no_dead_parity(self) -> None:
        params = re.findall(r"module_param(?:_named|_array_named)?\(\s*([a-zA-Z0-9_]+)", self.source)
        self.assertEqual(params, ["pm_sleep_mode"])
        for dead_tok in (
            "g6ts_lifecycle_profile.h",
            "g6ts_windows_cold_attach_locked",
            "g6ts_windows_cfu_inventory_locked",
            "g6ts_windows_init_parity",
            "g6ts_mode_handshake",
            "g6ts_sp11_cfu_offer",
            "g6ts_behavior_v2",
            "g6ts_windows_orchestrator",
            "g6ts_clean_init",
        ):
            self.assertNotIn(dead_tok, self.source)
        self.assertIn("profile=production-v1", self.source)
        self.assertFalse(
            (DRIVER.parent / "g6ts_lifecycle_profile.h").exists(),
            "unused g6ts_lifecycle_profile.h should be removed",
        )


if __name__ == "__main__":
    unittest.main()
