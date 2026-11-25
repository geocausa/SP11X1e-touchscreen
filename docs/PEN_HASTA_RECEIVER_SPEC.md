# SP11 OLED MPP 2.6 ("Hasta") Pen Receiver & `Col07` Technical Specification

> **Status: Offline Clean-Room Research Specification (Not Yet Validated on Physical Pen Hardware)**
>
> This specification documents the mathematical algorithms, wire layouts,
> calibration constants, error-detection codes, and palm-rejection geometry for
> the Surface Pro 11 OLED (`MSHW0485`, `VID=0x045E`, `PID=0x0C83`) pen stack.
> It is an independently authored clean-room engineering reference intended to
> accelerate Linux pen bring-up once a physical Surface Pen is available.
> **No kernel driver behavior is changed by this document, and no physical pen
> testing has been performed yet.**

---

## 1. Two Pen Operating Modes

| Mode | Controlled By | Touch Path | Pen Path |
| --- | --- | --- | --- |
| **Fallback (`PRE_OS`)** | `Col02 Feature 0x05 = 0` | `Col04` (`RepID 0x40`, 6B single-touch) | **`Col07` (`RepID 0x01`, 16B standard HID Pen)** decoded on-chip by firmware (`X 0..9600`, `Y 0..7200`, `Pressure 0..4096`, `XTilt/YTilt -90..+90 deg`, `ScanTime`, `Tip/InRange/Barrel/Invert/Eraser`) |
| **HEAT (Normal)** | `Col02 Feature 0x05 = 1` | `Col02` CapImg `0x0100` (`46x68` capacitive heatmap) | **`Col02` CapImg `0xFF00` (CCP sub-sections)** streaming raw antenna magnitudes, DFT windows, and metadata for host-side MPP 2.6 ("Hasta") decoding |

**Bring-up recommendation when a physical pen is available:**
1. First test `Col07` (`Feature 0x05 = 0`) to confirm basic stylus coordinates/buttons and verify whether firmware ever emits `Col07` alongside HEAT or strictly in fallback mode.
2. Then capture paired raw `0xFF00` CCP frames on Linux + OS pen reports on Windows to validate the host-side Hasta receiver equations below against real hardware before writing any kernel pen driver.

---

## 2. CapImg `0xFF00` CCP Sub-Section Wire Format

After stripping the 7-byte CapImg section header (`u32 Size, u16 0xFF00, u8 Version`), the vendor payload contains up to 100 concatenated CCP sub-sections:

```text
Offset  Size  Field
+0x00   u8    SectionId    (0xFF = padding/end; SectionId==0 && PayloadSize==0 = end)
+0x01   u8    Flags
+0x02   u16   PayloadSize  (LE byte count following this 4-byte header)
+0x04   ...   Payload      (advance offset by 4 + PayloadSize)
```

### 2.1 Core Pen CCP Sections

| `SectionId` | Role | Exact Payload Size / Layout |
| :---: | --- | --- |
| `0x57` | General pen frame metadata | **64 bytes (`0x40`)**: `+0x04 u32 FrameCounter`, `+0x08 u32 Timestamp`, `+0x0C u16 CycleMode`, `+0x0E u8 LfGain`, `+0x0F u8 HfGain`. |
| `0x5B` | Antenna magnitude arrays | **`(shortAnt + longAnt + 2) * 4` bytes** (or half-resolution `((short>>1) + (long>>1) + 2) * 4`). On SP11 OLED (`46x68`): 8-byte prefix (`+0x08 u8` mode/flags) followed by `u32[46]` short-axis (row) magnitudes and `u32[68]` long-axis (column) magnitudes. |
| `0x5C` | Complex DFT window | **`12 + 96 * NumOfFreq` bytes**: `+0x04 u32 Timestamp`, `+0x08 u8 NumOfFreq`, `+0x09 u8 WindowId`, `+0x0A u16 Status/Mask`, `+0x0C u8 Meta`, `+0x0D u8 WindowType`, followed at `+0x10` by two axis banks of `48 * NumOfFreq` bytes each (`48` bytes per frequency bin; `u32` squared power at entry `+0x04`). |
| `0x5F` | Window metadata | **16 bytes (`0x10`)**: `+0x04 u32 Meta`, `+0x08 u8 WindowId`, `+0x09 u8 WindowType`, `+0x0A u8 Aux0`, `+0x0B u8 Aux1`. |
| `0x62` | Pen detection | **16 bytes (`0x10`)**: `+0x04..+0x0F` detection metrics, `+0x10 u8 ChipIdx (<9)`, `+0x11 u8 WindowId`, `+0x12 u8 WindowType (<17)`. |
| `0x63` | Pen lift notification | `+0x04` lift reason code (triggers state-machine reset to `WaitForPen`). |

### 2.2 `WindowType` to Role & Slot Allocation

Active pen windows use `WindowType` values `6..11`, mapped into 7 per-frame slots (`0..6`):

| `WindowType` | Role ID | Slot Index | Notes |
| :---: | :---: | :---: | --- |
| `6` | `0` | `0` | Digital downlink half-1 (8 bits) + resets dual-slot `WindowId` latch |
| `7` | `1` | `1` | Digital downlink half-2 (8 bits) |
| `8` | `2` | `6` | Auxiliary / ring or secondary window |
| `9` | `3` | `2` | Tip / primary carrier window |
| `10` | `4` | `3` or `4` | Two windows per cycle, split across slots `3` (first `WindowId`) and `4` (second `WindowId`) |
| `11` | `5` | `5` | Secondary / pressure window |

---

## 3. Position Receiver: 1D Antenna Centroid Estimators

Given a peak antenna index `k_peak` and local squared-power samples `P[i]` along an axis, three baseline-subtracted centroid estimators are used depending on signal regime (tip vs. interior ring vs. wide-beam hover):

1. **3-Point Power-Weighted Centroid (Tip & Near-Border Ring):**
   With configurable exponent `p` (effective power exponent `e = p / 2`, so `p = 2.0` uses linear power `P` and `p = 1.0` uses amplitude `sqrt(P)`):
   - `v_L = P[k_peak - 1]^e`, `v_C = P[k_peak]^e`, `v_R = P[k_peak + 1]^e`
   - `base = min(v_L, v_C, v_R)`
   - `w_L = v_L - base`, `w_C = v_C - base`, `w_R = v_R - base`, `S = w_L + w_C + w_R`
   - If `S == 0`, return invalid (`-1.0`); else:
     `pos = ((k_peak - 1) * w_L + k_peak * w_C + (k_peak + 1) * w_R) / S`

2. **5-Point Squared-Amplitude Interior Ring Centroid:**
   From a 9-sample local amplitude window `a[0..8]`, compute `s[i] = a[i]^2`, take the 5-sample window around center `c` (`c-2..c+2`), subtract outer-edge baseline `base = min(s[c-2], s[c+2])`:
   - `w_m = s[c + m] - base` for `m in {-2, -1, 0, +1, +2}`
   - `pos = k_peak + (sum_{m=-2..2} m * w_m) / (sum_{m=-2..2} w_m)`

3. **5-Point `sqrt(P)` Minimum-Subtracted Hover/Wide-Beam Centroid:**
   For `m in {-2, -1, 0, +1, +2}` around `k_peak`:
   - `a_m = sqrt(P[k_peak + m])`, `base = min_m(a_m)`, `w_m = a_m - base`
   - `pos = (sum_{m=-2..2} (k_peak + m) * w_m) / (sum_{m=-2..2} w_m)`

---

## 4. Tilt & Azimuth Receiver

Tilt and azimuth are recovered from the horizontal displacement between the **tip** centroid `(x_tip, y_tip)` and the **ring** centroid `(x_ring, y_ring)` (in antenna units):

- `dx = x_ring - x_tip`, `dy = y_ring - y_tip`
- Physical antenna pitches on SP11 OLED (`273.89 mm x 182.59 mm`, `68 x 46` sensors):
  `pitch_x = 273.89 / 67 ~= 4.0879 mm`, `pitch_y = 182.59 / 45 ~= 4.0576 mm`.
- Validity guards: reject ring estimate if `|ring_peak_delta_x| > 2` or `|ring_peak_delta_y| > 2`, or if the centroid falls inside the configured border margin.

### 4.1 Pen Model Geometry Table (`inv_L = 1 / L_tip_ring`)

| Pen Geometry Class | Model IDs | `inv_L` (`mm^-1`) | Implied Tip-to-Ring Separation `L` (`mm`) | Neighbor Window | Scale |
| :---: | --- | :---: | :---: | :---: | :---: |
| `0` | Default | `0.13919821` | `7.184 mm` | `2` | `1.75` |
| `1` | `0x08`, `0x09`, `0x2D` | `0.13919821` | `7.184 mm` | `2` | `1.75` |
| `2` | `0x10` | `0.15174507` | `6.590 mm` | `2` | `1.75` |
| `3` | `0x13` | `0.10991668` | `9.098 mm` | `3` | `2.60` |

### 4.2 Polar Tilt & Azimuth Equations

1. **Physical horizontal tip-to-ring offset:**
   `dist_mm = max(0.0001, sqrt((dx * pitch_x)^2 + (dy * pitch_y)^2))`
2. **Polar tilt angle (`0..80.0 deg`, stored in centidegrees `0..8000`):**
   - `s = dist_mm * inv_L`
   - If `s > 1.0`: `tilt_deg = 80.0`
   - Else: `tilt_deg = clamp(asin(s) * (180 / pi), 0.0, 80.0)`
   - `tilt_centideg = round(tilt_deg * 100)`
3. **Azimuth angle (`[0, 360) deg`, stored in centidegrees `0..35999`):**
   - Apply panel axis orientation signs (`sign_x = flip_x ? -1 : +1`, `sign_y = flip_y ? +1 : -1`):
     `px = sign_x * dx * pitch_x`, `py = sign_y * dy * pitch_y`
   - `az_deg = atan2(py, px) * (180 / pi)`; if `az_deg < 0`, add `360.0`.
   - `az_centideg = round(az_deg * 100)`

### 4.3 Polar to HID / Linux Cartesian Tilt Projection

When formatting OS reports:
- Clamp `tilt_centideg <= 8999` (`89.99 deg`).
- Convert azimuth convention: `az_hid_rad = ((36000 - az_centideg) / 100.0) * (pi / 180.0)`.
- `t = tan(tilt_rad)`
- Standard (non-swapped) axes:
  - `x_tilt_deg = atan(cos(az_hid_rad) * t) * (180 / pi)` (or `sin`/`cos` swapped when `swap_xy == 1`)
  - `y_tilt_deg = atan(sin(az_hid_rad) * t) * (180 / pi)`
- Linux `evdev` reports `ABS_TILT_X` and `ABS_TILT_Y` in degrees (`-90..+90`, resolution `1` unit/deg or `57` units/rad); HID centidegrees scale by `100`.
- Enforce monotonic 16-bit `ScanTime`: if `new <= last` and `(last - new) < 150`, emit `(last + 1) & 0xFFFF`.

---

## 5. Pressure Receiver: Frequency Interpolation + Hybrid 10-bit Refinement

MPP 2.6 encodes coarse pressure as a resonant carrier frequency shift (~`23.3 kHz` at minimum force dropping down to ~`18.36 kHz` at full force) and refines it with 6 digital pressure bits.

### 5.1 Stage 1 — Coarse 8-bit Frequency-to-Pressure Index (`1..256`)

1. Across enabled pressure DFT bins `0..5`, select peak bin `k0 = argmax(power[b])` and stronger adjacent neighbor `k1 in {k0 - 1, k0 + 1}`.
2. Look up `(k0, k1)` in the 10-entry calibration table:

| Entry | `k0` | `k1` | `base_bin` | `norm_mode` | `c0` | `c1` | `c2` | `c3` (offset) |
| :---: | :---: | :---: | :---: | :---: | ---: | ---: | ---: | ---: |
| 0 | 5 | 4 | 3 | 1 (L1) | 0 | -525 | 629 | 22917 |
| 1 | 4 | 5 | 3 | 2 (L2) | 0 | 197 | 873 | 22203 |
| 2 | 4 | 3 | 3 | 1 (L1) | 12652 | 13845 | 0 | 8645 |
| 3 | 3 | 4 | 3 | 2 (L2) | 268 | 902 | 0 | 21059 |
| 4 | 3 | 2 | 1 | 1 (L1) | 12505 | 10806 | 12282 | 9147 |
| 5 | 2 | 3 | 1 | 2 (L2) | -100 | 319 | 993 | 19934 |
| 6 | 2 | 1 | 0 | 1 (L1) | 5822 | 4030 | 5526 | 14832 |
| 7 | 1 | 2 | 0 | 2 (L2) | -113 | 363 | 1004 | 18823 |
| 8 | 1 | 0 | 0 | 1 (L1) | 8675 | 9891 | 0 | 9399 |
| 9 | 0 | 1 | 0 | 2 (L2) | -68 | 680 | 0 | 18247 |

3. For `j in {0, 1, 2}` where `c_j != 0`, let `P_j = power[base_bin + j]` and `m_j = sqrt(P_j)`:
   - `num = sum(c_j * m_j)`
   - `den = sum(m_j)` if `norm_mode == 1`, or `sqrt(sum(P_j))` if `norm_mode == 2`.
   - `f_est = c3 + num / den` (equivalently `ratio = den / (c3 * den + num)`)
   - **`coarse = clamp(floor(ratio * 22054884.0 - 945.0 + 0.5), 1, 256)`**

### 5.2 Stage 2 — Hybrid 10-bit Digital Pressure Unwrapping (`0..1024`)

Given 6 decoded digital pressure bits `b[0..5]` (each gated by correlation magnitude `|corr_i| > sqrt(threshold)`):

- **6-bit digital-only mode:** If all 6 bits pass confidence, `p10 = (b0<<9)|(b1<<8)|(b2<<7)|(b3<<6)|(b4<<5)|(b5<<4)`; otherwise invalid (`0xFFFF`).
- **Hybrid analog+digital mode (standard MPP 2.5/2.6):**
  - Form 4-bit fine nibble `fine4 = (b0<<3)|(b1<<2)|(b2<<1)|b3` (`0..15`) and 2-bit finest LSB `lsb2 = (b4<<1)|b5` (`0..3`). (If bit `i` in `0..3` fails confidence, substitute `1` at that bit position.)
  - Full-scale saturation check: if `coarse == 256 && fine4 == 15 && b4 == 1 && b5 == 1`, return `1024`.
  - Otherwise clamp `coarse = min(coarse, 255)` and unwrap `fine4` onto the nearest 16-step bucket around `coarse`:
    1. `hi_a = coarse & 0xE0`, `hi_b = hi_a ^ 0x10`
    2. Pick `hi = hi_b` if `|hi_b + fine4 - coarse| < |hi_a + fine4 - coarse|` else `hi_a`.
    3. `cand = hi + fine4`
    4. If `cand - coarse > 7`: if `cand >= 16`, `cand -= 16`, else `cand = coarse`.
    5. Else if `cand - coarse < -7`: `cand += 16`.
    6. **`p10 = (cand << 2) | lsb2`** (`0..1024`; scaled to HID `0..4095` via pressure curve).

### 5.3 Stage 3 — User-Defined Pressure Curve (`CurveType`)

- `0`: Identity (`p`)
- `1`: Linear (`a * p + b`)
- `2`: Rational (`max(0, (a * p + b) / trunc(c * p + d))`, returning `1023.0` if denominator truncates to `0`).
- Final OS pressure clamped to `0..4095`.

---

## 6. Digital Downlink Pipeline: De-Interleaving, Hamming(16,11), CRC-4

### 6.1 Dual-Window 16-Bit Word Assembly

Digital downlink bits arrive across two consecutive 8-bit windows (`WindowType 6` and `WindowType 7`), each carrying two 4-bit nibbles stored in reversed bit order:

- `WindowType 6` (sets mask bit `0x1`):
  - Input bits `0..3` -> `word[15, 14, 13, 12]`
  - Input bits `4..7` -> `word[7, 6, 5, 4]`
- `WindowType 7` (sets mask bit `0x2`):
  - Input bits `0..3` -> `word[11, 10, 9, 8]`
  - Input bits `4..7` -> `word[3, 2, 1, 0]`

When both halves arrive (`mask == 0x3`), the 16-bit codeword `word[0..15]` is verified.

### 6.2 Extended Hamming(16, 11) Odd-Parity Verification

The 16 received bits `word[0..15]` map to Hamming buffer `h[0..15]` as:

- **Parity bits:** `h[15] = word[0]` (`p_overall`), `h[0] = word[1]` (`p1`), `h[1] = word[2]` (`p2`), `h[3] = word[3]` (`p4`), `h[7] = word[8]` (`p8`).
- **Data bits (11 bits):**
  - `word[4..7]` -> `h[2, 4, 5, 6]`
  - `word[9..15]` -> `h[8, 9, 10, 11, 12, 13, 14]`

All five parity checks use **odd parity** (initialized to `1`):
- `s1 = 1 ^ XOR(h[i] for i in {0, 2, 4, 6, 8, 10, 12, 14})`
- `s2 = 1 ^ XOR(h[i] for i in {1, 2, 5, 6, 9, 10, 13, 14})`
- `s4 = 1 ^ XOR(h[i] for i in {3, 4, 5, 6, 11, 12, 13, 14})`
- `s8 = 1 ^ XOR(h[i] for i in {7, 8, 9, 10, 11, 12, 13, 14})`
- `s_all = 1 ^ XOR(h[0..15])`

A codeword is **accepted only when `s1 == s2 == s4 == s8 == s_all == 0`** (pure error detection; corrupted frames are rejected to prevent phantom button presses or corrupted Pen IDs).

### 6.3 11-Bit Data Field & Message Dispatch

From an accepted codeword:
- **5-bit Message Type (`msg_type`):** `word[11..15]` (`word[11]` = bit 0 .. `word[15]` = bit 4; valid range `0x00..0x17`).
- **6-bit Payload (`payload[0..5]`):** `word[10, 9, 7, 6, 5, 4]` (reversed order).

| `msg_type` | Message | Payload Decoding |
| :---: | --- | --- |
| `0x00`, `0x01` | Generic 36-bit message | 6 consecutive 6-bit chunks + ITU-T CRC-4 |
| `0x02` | Status / Battery / ACK | `sub = (p[0]<<2)\|(p[1]<<1)\|p[2]`; when `sub == 1` (battery): `level = (p[3]<<2)\|(p[4]<<1)\|p[5]` (`0` maps to `5`) |
| `0x04`, `0x05` | Local ID | 3-bit ID `= ((msg_type & 1) << 2) \| (p[0] << 1) \| p[1]` |
| `0x06` | Buttons | `code = (p[0] << 1) \| p[1]`: `0` = none, `1` = eraser/invert (`3`), `2` = barrel (`2`), `3` = invalid/both |
| `0x16`, `0x17` | 32-bit Pen ID | 6 consecutive 6-bit chunks starting on `0x17` followed by 5x `0x16` -> 36 bits = 4-bit CRC (`bits[0..3]`) + 32-bit Pen ID (`bits[4..35]`) |

### 6.4 ITU-T CRC-4 Verification (32-Bit Pen ID & Generic Messages)

4-bit LFSR with polynomial **`x^4 + x + 1` (`0x13`)**, initialized to `0`:
- Shift through `bits[4..35]` (32 data bits):
  `fb = bit ^ r3; (r3, r2, r1, r0) = (r2, r1, r0 ^ fb, fb)`
- Valid iff `bits[0..3] == [r3, r2, r1, r0]`.

---

## 7. Pen-Aware Azimuth-Sector Radial Palm Rejection

When a valid pen contact `(pen_x, pen_y)` is active:
1. Convert `azimuth_centideg` to integer degrees `az = floor(azimuth_centideg / 100)` (`0..359`).
2. Construct the angular exclusion wedge `[az_start, az_end]` (mod `360`):
   - If `tilt > 0` and `azimuth != 0xFFFF`: `az_start = (az - span_left) mod 360`, `az_end = (az + span_right) mod 360` (using handedness-specific spans).
   - If vertical (`tilt == 0`): derive fallback wedge from device orientation angle + handedness offset (`+90 deg` for alternate handedness).
3. For each touch blob `(bx, by)`, compute bearing `theta = atan2_deg(by - pen_y, bx - pen_x)` in `[0, 360)`.
4. Suppress the touch blob if `((theta - az_start) mod 360) <= ((az_end - az_start) mod 360)` (inside the trailing-hand wedge) and within the active radial distance / timeout window.

---

## 8. Remaining Validation Required With a Physical Pen

Before merging any pen code into `mshw0485_touch.c`:
1. Capture paired raw `0xFF00` CCP streams + Windows OS pen reports across hover, light/heavy pressure, 4-quadrant tilt/azimuth, barrel/eraser buttons, fast strokes, and lift/suspend/resume.
2. Verify axis sign conventions (`flip_x`, `flip_y`, `swap_xy`), `DFT` entry offsets (`0x5C` byte stride), and pressure calibration curve scaling (`0..1024` -> `0..4095`) on actual hardware.
3. Test `Col07` fallback behavior (`Feature 0x05 = 0`) vs. HEAT mode (`Feature 0x05 = 1`) with a physical stylus.
