#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Offline clean-room MPP 2.6 ("Hasta") pen receiver prototype for SP11 OLED.

Implements the documented mathematical pipeline from docs/PEN_HASTA_RECEIVER_SPEC.md:
- CapImg 0xFF00 CCP section parsing (0x57, 0x5B, 0x5C, 0x5F, 0x62, 0x63)
- WindowType 6..11 role & 7-slot allocation
- 1D antenna centroid estimators (3-pt power-weighted, 5-pt ring, 5-pt sqrt hover)
- Tip-to-ring polar tilt & azimuth + HID Cartesian projection + monotonic ScanTime
- 10-entry frequency pressure interpolation + hybrid 10-bit digital unwrapping + curves
- Dual-window de-interleaving, Extended Hamming(16,11) odd-parity verification,
  ITU-T CRC-4 (x^4 + x + 1), buttons, local ID, battery, and 32-bit Pen ID reassembly
- Pen-aware azimuth-sector radial palm rejection

STATUS: Offline research prototype only. Not validated on a physical Surface Pen
and not wired into the Linux kernel touchscreen driver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import struct
from typing import Iterable, Sequence

# SP11 OLED physical geometry (from Feature 0x06: 46x68, 27389x18259 HIMETRIC)
SP11_SHORT_ANTENNAS = 46
SP11_LONG_ANTENNAS = 68
SP11_PITCH_X_MM = 273.89 / (SP11_LONG_ANTENNAS - 1)
SP11_PITCH_Y_MM = 182.59 / (SP11_SHORT_ANTENNAS - 1)

# Pen hardware geometry table: model_class -> (inv_L_mm^-1, neighbor_win, scale)
PEN_MODEL_GEOMETRY: dict[int, tuple[float, int, float]] = {
    0: (0.13919821, 2, 1.75),  # default (~7.184 mm)
    1: (0.13919821, 2, 1.75),  # models 0x08, 0x09, 0x2D
    2: (0.15174507, 2, 1.75),  # model 0x10 (~6.590 mm)
    3: (0.10991668, 3, 2.60),  # model 0x13 (~9.098 mm)
}

# Coarse frequency-to-pressure calibration table:
# (k0, k1): (base_bin, norm_mode, c0, c1, c2, c3_offset)
PRESSURE_FREQ_TABLE: dict[tuple[int, int], tuple[int, int, int, int, int, int]] = {
    (5, 4): (3, 1, 0, -525, 629, 22917),
    (4, 5): (3, 2, 0, 197, 873, 22203),
    (4, 3): (3, 1, 12652, 13845, 0, 8645),
    (3, 4): (3, 2, 268, 902, 0, 21059),
    (3, 2): (1, 1, 12505, 10806, 12282, 9147),
    (2, 3): (1, 2, -100, 319, 993, 19934),
    (2, 1): (0, 1, 5822, 4030, 5526, 14832),
    (1, 2): (0, 2, -113, 363, 1004, 18823),
    (1, 0): (0, 1, 8675, 9891, 0, 9399),
    (0, 1): (0, 2, -68, 680, 0, 18247),
}

PRESSURE_F0 = 945.0
PRESSURE_F1 = 22054884.0
TILT_MAX_DEG = 80.0
TILT_DIST_MIN_MM = 0.0001

WINDOW_TYPE_TO_ROLE: dict[int, int] = {
    6: 0,
    7: 1,
    8: 2,
    9: 3,
    10: 4,
    11: 5,
}


def pen_model_class(model_id: int) -> int:
    if model_id in (0x08, 0x09, 0x2D):
        return 1
    if model_id == 0x10:
        return 2
    if model_id == 0x13:
        return 3
    return 0


class SlotAllocator:
    """Maps (window_type, window_id) into the 7 per-frame pen window slots."""

    def __init__(self) -> None:
        self._expect_first_type10 = True
        self._first_type10_id = 0

    def slot_for(self, window_type: int, window_id: int) -> int:
        if window_type == 6:
            self._expect_first_type10 = True
            return 0
        if window_type == 7:
            return 1
        if window_type == 9:
            return 2
        if window_type == 10:
            if self._expect_first_type10:
                self._first_type10_id = window_id
                self._expect_first_type10 = False
                return 3
            return 3 if window_id == self._first_type10_id else 4
        if window_type == 11:
            return 5
        if window_type == 8:
            return 6
        return 7  # invalid


# ---------------------------------------------------------------------------
# CCP 0xFF00 section parsers
# ---------------------------------------------------------------------------


@dataclass
class PenMagnitudeSection:
    mode_flags: int
    short_axis: list[int]
    long_axis: list[int]


def parse_ccp_magnitude_section(
    section_bytes: bytes,
    short_ant: int = SP11_SHORT_ANTENNAS,
    long_ant: int = SP11_LONG_ANTENNAS,
) -> PenMagnitudeSection:
    """Parse CCP section 0x5B starting at its 4-byte CCP header."""
    if len(section_bytes) < 12:
        raise ValueError("magnitude section truncated")
    sec_id, _flags, payload_len = struct.unpack_from("<BBH", section_bytes, 0)
    if sec_id != 0x5B:
        raise ValueError(f"unexpected section id 0x{sec_id:02x}")
    full_len = (short_ant + long_ant + 2) * 4
    half_len = ((short_ant >> 1) + (long_ant >> 1) + 2) * 4
    if payload_len == full_len:
        s_cnt, l_cnt = short_ant, long_ant
    elif payload_len == half_len:
        s_cnt, l_cnt = short_ant >> 1, long_ant >> 1
    else:
        raise ValueError(f"invalid magnitude payload_len={payload_len}")
    if len(section_bytes) < 4 + payload_len:
        raise ValueError("magnitude buffer shorter than payload_len")
    mode_flags = section_bytes[8]
    short_axis = list(struct.unpack_from(f"<{s_cnt}I", section_bytes, 12))
    long_axis = list(
        struct.unpack_from(f"<{l_cnt}I", section_bytes, 12 + s_cnt * 4)
    )
    return PenMagnitudeSection(mode_flags, short_axis, long_axis)


# ---------------------------------------------------------------------------
# 1D Antenna Centroid Estimators
# ---------------------------------------------------------------------------


def centroid_3pt_power(
    powers: Sequence[int], peak_idx: int, peak_ant: int, exponent_p: float = 2.0
) -> float:
    """3-point power-weighted baseline-subtracted centroid (0x18002a5f8)."""
    if peak_idx < 1 or peak_idx + 1 >= len(powers):
        return -1.0
    e = exponent_p * 0.5
    v_l = float(powers[peak_idx - 1]) ** e
    v_c = float(powers[peak_idx]) ** e
    v_r = float(powers[peak_idx + 1]) ** e
    base = min(v_l, v_c, v_r)
    w_l, w_c, w_r = v_l - base, v_c - base, v_r - base
    total = w_l + w_c + w_r
    if total == 0.0:
        return -1.0
    return ((peak_ant - 1) * w_l + peak_ant * w_c + (peak_ant + 1) * w_r) / total


def centroid_5pt_ring_sq(
    amplitudes: Sequence[float], center_idx: int, peak_ant: int
) -> float:
    """5-point squared-amplitude interior ring centroid (0x18002a708)."""
    if center_idx < 2 or center_idx + 2 >= len(amplitudes):
        return -1.0
    sq = [float(a) * float(a) for a in amplitudes]
    base = min(sq[center_idx - 2], sq[center_idx + 2])
    num = 0.0
    den = 0.0
    for offset in range(-2, 3):
        w = sq[center_idx + offset] - base
        num += offset * w
        den += w
    if den == 0.0:
        return -1.0
    return peak_ant + (num / den)


def centroid_5pt_sqrt_hover(
    powers: Sequence[int], center_idx: int, peak_ant: int
) -> float:
    """5-point sqrt(P) min-subtracted wide-beam centroid (0x18002a900)."""
    if center_idx < 2 or center_idx + 2 >= len(powers):
        return -1.0
    amps = [math.sqrt(float(powers[center_idx + m])) for m in range(-2, 3)]
    base = min(amps)
    weights = [a - base for a in amps]
    den = sum(weights)
    if den == 0.0:
        return -1.0
    num = sum((peak_ant + m) * weights[m + 2] for m in range(-2, 3))
    return num / den


# ---------------------------------------------------------------------------
# Tilt & Azimuth + HID Cartesian Projection
# ---------------------------------------------------------------------------


def calculate_polar_tilt_azimuth(
    dx_ant: float,
    dy_ant: float,
    model_id: int = 0,
    pitch_x_mm: float = SP11_PITCH_X_MM,
    pitch_y_mm: float = SP11_PITCH_Y_MM,
    flip_x: bool = False,
    flip_y: bool = False,
) -> tuple[int, int]:
    """Compute polar (tilt_centideg [0..8000], azimuth_centideg [0..35999])."""
    inv_l, _, _ = PEN_MODEL_GEOMETRY[pen_model_class(model_id)]
    px_abs = dx_ant * pitch_x_mm
    py_abs = dy_ant * pitch_y_mm
    dist_mm = max(TILT_DIST_MIN_MM, math.hypot(px_abs, py_abs))
    sin_theta = dist_mm * inv_l
    if sin_theta > 1.0:
        tilt_deg = TILT_MAX_DEG
    else:
        tilt_deg = min(TILT_MAX_DEG, max(0.0, math.degrees(math.asin(sin_theta))))
    tilt_cdeg = int(round(tilt_deg * 100.0))

    sign_x = -1.0 if flip_x else 1.0
    sign_y = 1.0 if flip_y else -1.0
    az_deg = math.degrees(math.atan2(sign_y * py_abs, sign_x * px_abs))
    if az_deg < 0.0:
        az_deg += 360.0
    az_cdeg = int(round(az_deg * 100.0)) % 36000
    return tilt_cdeg, az_cdeg


def polar_to_cartesian_tilt_centideg(
    tilt_centideg: int,
    azimuth_centideg: int,
    swap_xy: bool = False,
) -> tuple[int, int]:
    """Convert polar (tilt, azimuth) in centidegrees to HID Cartesian XTilt/YTilt."""
    if tilt_centideg == 0xFFFF or azimuth_centideg == 0xFFFF:
        return 0, 0
    clamped = min(tilt_centideg, 8999)
    t = math.tan(math.radians(clamped / 100.0))
    az_hid = math.radians((36000.0 - azimuth_centideg) / 100.0)
    s_az = math.sin(az_hid)
    c_az = math.cos(az_hid)
    if swap_xy:
        a = math.degrees(math.atan(s_az * t))
        b = math.degrees(math.atan(c_az * t))
    else:
        a = math.degrees(math.atan(c_az * t))
        b = math.degrees(math.atan(s_az * t))
    return int(b * 100.0), int(a * 100.0)


def enforce_monotonic_scantime(new_scantime: int, last_scantime: int) -> int:
    """Enforce monotonic 16-bit ScanTime with 150-tick backward guard."""
    new_u16 = new_scantime & 0xFFFF
    if new_u16 <= last_scantime and (last_scantime - new_u16) < 150:
        return (last_scantime + 1) & 0xFFFF
    return new_u16


# ---------------------------------------------------------------------------
# Pressure: Frequency Interpolation + Hybrid 10-bit Digital Unwrap + Curves
# ---------------------------------------------------------------------------


def select_pressure_bins(
    bin_powers: Sequence[int], valid_mask: int = 0x3F
) -> tuple[int, int]:
    """Select primary peak bin k0 and stronger adjacent neighbor k1 in 0..5."""
    k0 = 0
    best = -1
    for b in range(6):
        if (valid_mask >> b) & 1:
            if bin_powers[b] > best:
                best = bin_powers[b]
                k0 = b
    if k0 == 0:
        return (0, 1)
    if k0 == 5:
        return (5, 4)
    left_ok = bool((valid_mask >> (k0 - 1)) & 1)
    right_ok = bool((valid_mask >> (k0 + 1)) & 1)
    if left_ok and right_ok:
        k1 = (k0 - 1) if bin_powers[k0 - 1] >= bin_powers[k0 + 1] else (k0 + 1)
    elif right_ok:
        k1 = k0 + 1
    else:
        k1 = k0 - 1
    return (k0, k1)


def calculate_coarse_pressure_index(
    bin_powers: Sequence[int], valid_mask: int = 0x3F
) -> int:
    """Compute coarse 8-bit pressure index (1..256) from 6 DFT bin powers."""
    k0, k1 = select_pressure_bins(bin_powers, valid_mask)
    base_bin, norm_mode, c0, c1, c2, c3 = PRESSURE_FREQ_TABLE[(k0, k1)]
    coeffs = (c0, c1, c2)
    num = 0.0
    den = 0.0
    for j, c in enumerate(coeffs):
        if c == 0:
            continue
        p = float(bin_powers[base_bin + j])
        m = math.sqrt(p)
        num += c * m
        if norm_mode == 2:
            den += p
        else:
            den += m
    if norm_mode == 2:
        den = math.sqrt(den)
    if den <= 0.0:
        return 1
    f_denom = c3 * den + num
    if f_denom <= 0.0:
        return 256
    ratio = den / f_denom
    raw_idx = int(math.floor(ratio * PRESSURE_F1 - PRESSURE_F0 + 0.5))
    return max(1, min(256, raw_idx))


def combine_hybrid_pressure_10bit(
    coarse_1_to_256: int,
    bits: Sequence[int],
    bit_valid: Sequence[bool] | None = None,
    digital_only_6bit: bool = False,
) -> int:
    """Combine coarse frequency pressure (1..256) with 6 digital bits -> 0..1024."""
    if len(bits) != 6:
        raise ValueError("expected 6 digital pressure bits")
    valid = [True] * 6 if bit_valid is None else list(bit_valid)
    if digital_only_6bit:
        if not all(valid):
            return 0xFFFF
        val = 0
        for i in range(6):
            val |= (bits[i] & 1) << (9 - i)
        return val

    fine4 = 0
    for i in range(4):
        bit = (bits[i] & 1) if valid[i] else 1
        fine4 |= bit << (3 - i)

    b4 = bits[4] & 1
    b5 = bits[5] & 1
    coarse = coarse_1_to_256
    if coarse == 256 and fine4 == 0xF and b4 == 1 and b5 == 1:
        return 1024
    if coarse == 256:
        coarse = 255

    if valid[0] or valid[1] or valid[2]:
        hi_a = coarse & 0xE0
        hi_b = hi_a ^ 0x10
        err_a = abs((hi_a + fine4) - coarse)
        err_b = abs((hi_b + fine4) - coarse)
        hi = hi_b if err_b < err_a else hi_a
        cand = hi + fine4
        delta = cand - coarse
        if delta > 7:
            coarse = (cand - 16) if cand >= 16 else coarse
        elif delta < -7:
            coarse = cand + 16
        else:
            coarse = cand

    return ((coarse & 0xFF) << 2) | (b4 << 1) | b5


def apply_pressure_curve(
    pressure: float,
    curve_type: int,
    a: int = 1,
    b: int = 0,
    c: int = 0,
    d: int = 1,
) -> float:
    """Apply user-defined pressure curve (0=identity, 1=linear, 2=rational)."""
    if curve_type == 0:
        return pressure
    if curve_type == 1:
        return float(a) * pressure + float(b)
    if curve_type == 2:
        denom = int(float(c) * pressure + float(d))
        if denom == 0:
            return 1023.0
        val = (float(a) * pressure + float(b)) / float(denom)
        return float(int(max(0.0, val)) & 0xFFFF)
    return pressure


# ---------------------------------------------------------------------------
# Digital Downlink: De-Interleave, Extended Hamming(16,11), ITU-T CRC-4
# ---------------------------------------------------------------------------


def deinterleave_downlink_windows(
    win6_bits: Sequence[int], win7_bits: Sequence[int]
) -> list[int]:
    """Assemble 16-bit codeword word[0..15] from WindowType 6 and 7 (8 bits each)."""
    if len(win6_bits) != 8 or len(win7_bits) != 8:
        raise ValueError("each downlink half-window must contain 8 bits")
    word = [0] * 16
    for i in range(4):
        word[15 - i] = win6_bits[i] & 1
        word[7 - i] = win6_bits[4 + i] & 1
        word[11 - i] = win7_bits[i] & 1
        word[3 - i] = win7_bits[4 + i] & 1
    return word


def encode_hamming16_11_odd(msg_type: int, payload_bits: Sequence[int]) -> list[int]:
    """Construct a valid odd-parity Extended Hamming(16,11) codeword word[0..15]."""
    if not (0 <= msg_type <= 31) or len(payload_bits) != 6:
        raise ValueError("invalid msg_type or payload_bits")
    word = [0] * 16
    # Message type in word[11..15] (LSB at word[11])
    for i in range(5):
        word[11 + i] = (msg_type >> i) & 1
    # Reversed 6-bit payload in word[10, 9, 7, 6, 5, 4]
    payload_positions = (10, 9, 7, 6, 5, 4)
    for idx, wpos in enumerate(payload_positions):
        word[wpos] = payload_bits[idx] & 1

    # Map data bits into Hamming positions h[0..15]
    h = [0] * 16
    for src, dst in zip((4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15),
                        (2, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14)):
        h[dst] = word[src]

    # Compute odd-parity bits p1(h[0]), p2(h[1]), p4(h[3]), p8(h[7]), p0(h[15])
    h[0] = 1 ^ h[2] ^ h[4] ^ h[6] ^ h[8] ^ h[10] ^ h[12] ^ h[14]
    h[1] = 1 ^ h[2] ^ h[5] ^ h[6] ^ h[9] ^ h[10] ^ h[13] ^ h[14]
    h[3] = 1 ^ h[4] ^ h[5] ^ h[6] ^ h[11] ^ h[12] ^ h[13] ^ h[14]
    h[7] = 1 ^ h[8] ^ h[9] ^ h[10] ^ h[11] ^ h[12] ^ h[13] ^ h[14]
    h[15] = 1
    for i in range(15):
        h[15] ^= h[i]

    word[0] = h[15]
    word[1] = h[0]
    word[2] = h[1]
    word[3] = h[3]
    word[8] = h[7]
    return word


def verify_hamming16_11_odd(word: Sequence[int]) -> bool:
    """Verify odd-parity Extended Hamming(16,11) codeword (0x1800217f0)."""
    if len(word) != 16:
        return False
    h = [0] * 16
    h[15] = word[0] & 1
    h[0] = word[1] & 1
    h[1] = word[2] & 1
    h[3] = word[3] & 1
    h[7] = word[8] & 1
    for src, dst in zip((4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15),
                        (2, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14)):
        h[dst] = word[src] & 1

    s1 = 1
    s2 = 1
    s4 = 1
    s8 = 1
    s_all = 1
    for idx in range(16):
        bit = h[idx]
        s_all ^= bit
        if idx < 15:
            pos1 = idx + 1
            if pos1 & 1:
                s1 ^= bit
            if pos1 & 2:
                s2 ^= bit
            if pos1 & 4:
                s4 ^= bit
            if pos1 & 8:
                s8 ^= bit
    return (s1 | s2 | s4 | s8 | s_all) == 0


def parse_digital_word(word: Sequence[int]) -> tuple[int, list[int]]:
    """Extract (msg_type [0..31], payload_bits[0..5]) from verified 16-bit word."""
    msg_type = 0
    for i in range(5):
        msg_type |= (word[11 + i] & 1) << i
    payload = [word[p] & 1 for p in (10, 9, 7, 6, 5, 4)]
    return msg_type, payload


def compute_crc4_itut(data_32_bits: Sequence[int]) -> list[int]:
    """Compute 4-bit ITU-T CRC-4 (x^4 + x + 1, init 0) over 32 bits (0x180021678)."""
    if len(data_32_bits) != 32:
        raise ValueError("CRC-4 expects 32 data bits")
    r0 = r1 = r2 = r3 = 0
    for b in data_32_bits:
        fb = (b & 1) ^ r3
        r3, r2, r1, r0 = r2, r1, r0 ^ fb, fb
    return [r3, r2, r1, r0]


def check_crc4_itut(bits_36: Sequence[int]) -> bool:
    """Verify 36-bit Pen ID / generic message: bits[0..3] == CRC4(bits[4..35])."""
    if len(bits_36) != 36:
        return False
    return list(bits_36[:4]) == compute_crc4_itut(bits_36[4:])


def decode_buttons_payload(payload_bits: Sequence[int]) -> dict[str, int | bool]:
    """Decode msg_type=0x06 buttons payload (0x180022170)."""
    code = ((payload_bits[0] & 1) << 1) | (payload_bits[1] & 1)
    return {
        "raw_code": code,
        "barrel": code == 2,
        "eraser": code == 1,
        "none": code == 0,
    }


def decode_status_battery(payload_bits: Sequence[int]) -> int | None:
    """Decode msg_type=0x02 status payload -> battery level 1..7 or None."""
    sub = ((payload_bits[0] & 1) << 2) | ((payload_bits[1] & 1) << 1) | (payload_bits[2] & 1)
    if sub != 1:
        return None
    lvl = ((payload_bits[3] & 1) << 2) | ((payload_bits[4] & 1) << 1) | (payload_bits[5] & 1)
    return 5 if lvl == 0 else lvl


def decode_local_id(msg_type: int, payload_bits: Sequence[int]) -> int:
    """Decode msg_type=0x04/0x05 -> 3-bit Local ID (0..7)."""
    return ((msg_type & 1) << 2) | ((payload_bits[0] & 1) << 1) | (payload_bits[1] & 1)


@dataclass
class PenIdAssembler:
    """Reassemble 32-bit Pen ID from 6 consecutive 6-bit chunks (0x17 + 5x 0x16)."""

    chunks: list[int] = field(default_factory=list)
    last_cycle: int | None = None

    def reset(self) -> None:
        self.chunks.clear()
        self.last_cycle = None

    def feed(self, msg_type: int, payload_bits: Sequence[int], cycle: int) -> int | None:
        if msg_type == 0x17:
            self.chunks = [b & 1 for b in payload_bits]
            self.last_cycle = cycle
            return None
        if msg_type != 0x16 or not self.chunks:
            self.reset()
            return None
        if self.last_cycle is not None and cycle != self.last_cycle + 1:
            self.reset()
            return None
        self.chunks.extend(b & 1 for b in payload_bits)
        self.last_cycle = cycle
        if len(self.chunks) < 36:
            return None
        bits = self.chunks[:36]
        self.reset()
        if not check_crc4_itut(bits):
            return None
        pen_id = 0
        for b in bits[4:]:
            pen_id = (pen_id << 1) | b
        return pen_id


# ---------------------------------------------------------------------------
# Pen-Aware Azimuth-Sector Radial Palm Rejection
# ---------------------------------------------------------------------------


def is_touch_in_pen_palm_sector(
    pen_x_mm: float,
    pen_y_mm: float,
    blob_x_mm: float,
    blob_y_mm: float,
    tilt_centideg: int,
    azimuth_centideg: int,
    span_left_deg: int = 70,
    span_right_deg: int = 70,
    max_radius_mm: float = 140.0,
    fallback_orient_deg: int = 0,
    left_handed: bool = False,
) -> bool:
    """Return True if a touch blob falls inside the pen's trailing-hand wedge."""
    dx = blob_x_mm - pen_x_mm
    dy = blob_y_mm - pen_y_mm
    dist = math.hypot(dx, dy)
    if dist > max_radius_mm:
        return False

    if tilt_centideg > 0 and azimuth_centideg != 0xFFFF:
        az = azimuth_centideg // 100
        start = (az - span_left_deg) % 360
        end = (az + span_right_deg) % 360
    else:
        base = fallback_orient_deg + (90 if left_handed else 0)
        start = (base - span_left_deg) % 360
        end = (base + span_right_deg) % 360

    theta = int(math.degrees(math.atan2(dy, dx))) % 360
    rel_theta = (theta - start) % 360
    rel_end = (end - start) % 360
    return rel_theta <= rel_end


if __name__ == "__main__":
    print("SP11 MPP 2.6 Hasta offline prototype module (run tests/test_pen_hasta_prototype.py)")
