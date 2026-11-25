#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Synthetic unit tests for the offline MPP 2.6 ("Hasta") pen receiver prototype.

NOTE: These tests exercise the documented offline mathematical pipeline with
synthetic inputs. They do not substitute for live physical Surface Pen testing.
"""

from __future__ import annotations

import math
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pen_hasta_prototype as hp  # noqa: E402


class PenHastaPrototypeTests(unittest.TestCase):
    def test_slot_allocator_window_types_and_dual_type10(self) -> None:
        alloc = hp.SlotAllocator()
        self.assertEqual(alloc.slot_for(6, 0x10), 0)
        self.assertEqual(alloc.slot_for(7, 0x11), 1)
        self.assertEqual(alloc.slot_for(9, 0x12), 2)
        self.assertEqual(alloc.slot_for(10, 0x20), 3)
        self.assertEqual(alloc.slot_for(10, 0x20), 3)
        self.assertEqual(alloc.slot_for(10, 0x21), 4)
        self.assertEqual(alloc.slot_for(11, 0x30), 5)
        self.assertEqual(alloc.slot_for(8, 0x40), 6)
        self.assertEqual(alloc.slot_for(5, 0x00), 7)  # invalid
        # WindowType 6 resets dual-slot type-10 latch for next cycle
        self.assertEqual(alloc.slot_for(6, 0x50), 0)
        self.assertEqual(alloc.slot_for(10, 0x99), 3)
        self.assertEqual(alloc.slot_for(10, 0x9A), 4)

    def test_ccp_magnitude_section_full_and_half_res(self) -> None:
        # Full resolution: (46 + 68 + 2) * 4 = 464 bytes
        short_vals = [100 + i for i in range(46)]
        long_vals = [500 + i for i in range(68)]
        payload = struct.pack("<IBBBB", 0x11223344, 0x05, 0, 0, 0) + struct.pack(
            f"<46I68I", *short_vals, *long_vals
        )
        sec = struct.pack("<BBH", 0x5B, 0x01, len(payload)) + payload
        parsed = hp.parse_ccp_magnitude_section(sec)
        self.assertEqual(parsed.mode_flags, 0x05)
        self.assertEqual(parsed.short_axis, short_vals)
        self.assertEqual(parsed.long_axis, long_vals)

        # Half resolution: (23 + 34 + 2) * 4 = 236 bytes
        half_payload = struct.pack("<IBBBB", 0, 0x02, 0, 0, 0) + struct.pack(
            "<23I34I", *range(23), *range(34)
        )
        half_sec = struct.pack("<BBH", 0x5B, 0x01, len(half_payload)) + half_payload
        parsed_half = hp.parse_ccp_magnitude_section(half_sec)
        self.assertEqual(len(parsed_half.short_axis), 23)
        self.assertEqual(len(parsed_half.long_axis), 34)

        with self.assertRaises(ValueError):
            hp.parse_ccp_magnitude_section(struct.pack("<BBH", 0x5B, 0, 100) + bytes(100))

    def test_antenna_centroid_estimators(self) -> None:
        # Symmetric 3-pt peak -> exact integer peak
        self.assertAlmostEqual(
            hp.centroid_3pt_power([10, 100, 10], peak_idx=1, peak_ant=20, exponent_p=2.0),
            20.0,
            places=6,
        )
        # Asymmetric right-shifted 3-pt peak -> shifted right of peak_ant
        pos = hp.centroid_3pt_power([10, 100, 55], peak_idx=1, peak_ant=20, exponent_p=2.0)
        # w_L=0, w_C=90, w_R=45 -> 20 + 45/135 = 20.333333
        self.assertAlmostEqual(pos, 20.0 + 1.0 / 3.0, places=6)

        # Flat noise -> invalid (-1.0)
        self.assertEqual(hp.centroid_3pt_power([50, 50, 50], 1, 10), -1.0)

        # 5-pt ring squared-amplitude centroid
        ring_amps = [0.0, 0.0, 1.0, 2.0, 4.0, 2.0, 1.0, 0.0, 0.0]
        self.assertAlmostEqual(hp.centroid_5pt_ring_sq(ring_amps, 4, 15), 15.0, places=6)

        # 5-pt hover sqrt(P) centroid
        hover_p = [100, 400, 900, 400, 100]  # sqrt: [10, 20, 30, 20, 10]
        self.assertAlmostEqual(hp.centroid_5pt_sqrt_hover(hover_p, 2, 30), 30.0, places=6)

    def test_polar_tilt_azimuth_and_cartesian_hid_projection(self) -> None:
        # 30-degree tilt along +X for default model (L = 1/0.13919821 = 7.184 mm)
        # sin(30 deg) = 0.5 -> dist = 3.592 mm -> dx_ant = 3.592 / pitch_x
        dx_ant = (0.5 / hp.PEN_MODEL_GEOMETRY[0][0]) / hp.SP11_PITCH_X_MM
        tilt_cd, az_cd = hp.calculate_polar_tilt_azimuth(dx_ant, 0.0, model_id=0)
        self.assertAlmostEqual(tilt_cd, 3000, delta=2)
        self.assertEqual(az_cd, 0)

        # Saturation above L_tip_ring clamps at 80.0 deg (8000 centidegrees)
        sat_tilt, _ = hp.calculate_polar_tilt_azimuth(5.0, 5.0, model_id=0)
        self.assertEqual(sat_tilt, 8000)

        # Polar -> Cartesian HID tilt round-trip at 45 deg azimuth, 30 deg tilt
        xt, yt = hp.polar_to_cartesian_tilt_centideg(3000, 4500, swap_xy=False)
        self.assertEqual(abs(xt), abs(yt))
        self.assertGreater(abs(xt), 2000)
        self.assertLess(abs(xt), 2400)

        # Invalid sentinel 0xFFFF -> (0, 0)
        self.assertEqual(hp.polar_to_cartesian_tilt_centideg(0xFFFF, 1000), (0, 0))

        # Monotonic ScanTime guard
        self.assertEqual(hp.enforce_monotonic_scantime(100, 105), 106)
        self.assertEqual(hp.enforce_monotonic_scantime(100, 500), 100)  # wrap/jump >= 150

    def test_pressure_coarse_frequency_and_hybrid_10bit_unwrap(self) -> None:
        # Light touch near bin 5/4 (~23.5 kHz -> low coarse index)
        light_bins = [0, 0, 0, 100, 9000, 10000]
        p_light = hp.calculate_coarse_pressure_index(light_bins)
        # Heavy touch near bin 3/2 (higher effective frequency -> higher index)
        heavy_bins = [0, 2000, 12000, 15000, 100, 0]
        p_heavy = hp.calculate_coarse_pressure_index(heavy_bins)
        self.assertGreaterEqual(p_light, 1)
        self.assertLessEqual(p_heavy, 256)
        self.assertGreater(p_heavy, p_light)

        # Hybrid 10-bit saturation: coarse=256, all 6 bits = 1 -> 1024
        self.assertEqual(
            hp.combine_hybrid_pressure_10bit(256, [1, 1, 1, 1, 1, 1]), 1024
        )
        # Hybrid phase-unwrap across 16-step bucket boundary:
        # coarse = 33 (0x21), fine4 = 0xF (15) -> nearest 16-step match is 31 (0x1F)
        # p10 = (31 << 2) | 0b10 = 126
        self.assertEqual(
            hp.combine_hybrid_pressure_10bit(33, [1, 1, 1, 1, 1, 0]), (31 << 2) | 2
        )
        # 6-bit digital-only mode
        self.assertEqual(
            hp.combine_hybrid_pressure_10bit(10, [1, 0, 1, 0, 1, 0], digital_only_6bit=True),
            0b1010100000,
        )
        # User pressure curves
        self.assertEqual(hp.apply_pressure_curve(500.0, 0), 500.0)
        self.assertEqual(hp.apply_pressure_curve(100.0, 1, a=4, b=10), 410.0)
        self.assertEqual(hp.apply_pressure_curve(100.0, 2, a=1, b=0, c=0, d=0), 1023.0)

    def test_digital_deinterleave_hamming_crc4_and_messages(self) -> None:
        # Encode a barrel button message (msg_type=0x06, payload=[1, 0, 0, 0, 0, 0])
        word = hp.encode_hamming16_11_odd(0x06, [1, 0, 0, 0, 0, 0])
        self.assertTrue(hp.verify_hamming16_11_odd(word))

        # Verify de-interleaving matches inverse of WindowType 6 & 7 layout
        win6 = [word[15], word[14], word[13], word[12], word[7], word[6], word[5], word[4]]
        win7 = [word[11], word[10], word[9], word[8], word[3], word[2], word[1], word[0]]
        self.assertEqual(hp.deinterleave_downlink_windows(win6, win7), word)

        mtype, payload = hp.parse_digital_word(word)
        self.assertEqual(mtype, 0x06)
        btns = hp.decode_buttons_payload(payload)
        self.assertTrue(btns["barrel"])
        self.assertFalse(btns["eraser"])

        # Single-bit flip in ANY of the 16 positions must be rejected by Hamming check
        for flip_pos in range(16):
            corrupted = list(word)
            corrupted[flip_pos] ^= 1
            self.assertFalse(
                hp.verify_hamming16_11_odd(corrupted),
                f"bit flip at {flip_pos} was not detected",
            )

        # Battery status (msg_type=0x02, sub=1, lvl=0 -> mapped to 5)
        self.assertEqual(hp.decode_status_battery([0, 0, 1, 0, 0, 0]), 5)
        self.assertEqual(hp.decode_status_battery([0, 0, 1, 1, 1, 0]), 6)
        self.assertIsNone(hp.decode_status_battery([0, 1, 0, 1, 1, 1]))

        # Local ID (msg_type=0x05 -> bit2=1, payload=[1,0,...] -> 0b110 = 6)
        self.assertEqual(hp.decode_local_id(0x05, [1, 0, 0, 0, 0, 0]), 6)

        # 32-bit Pen ID + ITU-T CRC-4 reassembly across 6 consecutive cycles
        pen_id = 0x1234ABCD
        id_bits = [(pen_id >> (31 - i)) & 1 for i in range(32)]
        crc = hp.compute_crc4_itut(id_bits)
        bits_36 = crc + id_bits
        self.assertTrue(hp.check_crc4_itut(bits_36))

        asm = hp.PenIdAssembler()
        result = None
        for idx in range(6):
            mt = 0x17 if idx == 0 else 0x16
            chunk = bits_36[idx * 6 : (idx + 1) * 6]
            w = hp.encode_hamming16_11_odd(mt, chunk)
            self.assertTrue(hp.verify_hamming16_11_odd(w))
            parsed_mt, parsed_chunk = hp.parse_digital_word(w)
            result = asm.feed(parsed_mt, parsed_chunk, cycle=100 + idx)
        self.assertEqual(result, pen_id)

        # Corrupted CRC-4 must be rejected
        bad_36 = list(bits_36)
        bad_36[0] ^= 1
        self.assertFalse(hp.check_crc4_itut(bad_36))

    def test_pen_azimuth_sector_radial_palm_rejection(self) -> None:
        # Pen at (100, 100) mm tilted toward azimuth=0 deg (trailing palm at +X, 0 deg)
        # Palm at (150, 110) mm (~11 deg, dist ~51 mm) -> rejected
        self.assertTrue(
            hp.is_touch_in_pen_palm_sector(
                100.0, 100.0, 150.0, 110.0, tilt_centideg=3000, azimuth_centideg=0
            )
        )
        # Wraparound across 350 deg / 0 deg: palm at (150, 90) mm (~349 deg) -> rejected
        self.assertTrue(
            hp.is_touch_in_pen_palm_sector(
                100.0, 100.0, 150.0, 90.0, tilt_centideg=3000, azimuth_centideg=0
            )
        )
        # Intentional opposite-hand finger at (40, 100) mm (180 deg) -> NOT rejected
        self.assertFalse(
            hp.is_touch_in_pen_palm_sector(
                100.0, 100.0, 40.0, 100.0, tilt_centideg=3000, azimuth_centideg=0
            )
        )
        # Far outside radial limit (200 mm away) -> NOT rejected
        self.assertFalse(
            hp.is_touch_in_pen_palm_sector(
                100.0, 100.0, 260.0, 100.0, tilt_centideg=3000, azimuth_centideg=0
            )
        )


if __name__ == "__main__":
    unittest.main()
