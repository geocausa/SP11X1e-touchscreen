# Windows SPB live restart capture, 2026-08-04

## Result

A fresh Windows-side capture on the project Surface Pro 11 reproduces the
`MSHW0485` HID-SPI attach traffic with only built-in Windows tracing tools. The
capture was taken on Windows 11 build `26200` with `hidspi.sys`
`10.0.26100.8737`. The installed `TouchPenProcessor0C83.dll` remains version
`26.6.139.0` and has the same SHA-256 previously audited by this repository:

```text
615a28136f14678298dcd9f009c9295456a9e7ce878717b58d371d343b4c7132
```

The base ACPI device was restarted with `pnputil`; it returned to `Status=OK`
and `CM_PROB_NONE`. No firmware payload was sent by this project and no Linux
state was changed.

The fresh trace confirms three important existing conclusions:

- Windows still sends logical `SET_FEATURE 0x70 = {0x01}` with one content
  byte;
- A1/A5 report-`0x09` feedback remains 63 bytes and carries dynamic provider
  state rather than per-frame contact coordinates;
- CFU, device-configuration, and Heat/feedback owners can interleave in another
  valid order, so one observed Windows bus chronology must not be flattened
  into a synchronous Linux initialization recipe.

It also provides a current cadence cross-check. The short header-to-body delay
has a similar lower-percentile boundary to the Phase 91 reference, but a longer
scheduler tail. The important response-level invariant remains much stronger:
none of the 1,240 consecutive Heat responses starts another header within
1 ms of the preceding Heat body.

## Host identity

```text
Machine: Microsoft Surface Pro, 11th Edition
Architecture: ARM64
Windows: 10.0.26200, build 26200
Base device: ACPI\MSHW0485\2&DABA3FF&0
Base service: hidspi
hidspi.sys: 10.0.26100.8737
TouchPenProcessor0C83.dll: 26.6.139.0
TouchPenProcessor0C83.dll SHA-256:
615a28136f14678298dcd9f009c9295456a9e7ce878717b58d371d343b4c7132
```

The processor DLL identity exactly matches the binary used for the repository's
existing static TouchPenProcessor analysis, so those processing-side findings
still apply to this installed Windows stack.

## Capture method

The capture used the analytic keyword of the built-in
`Microsoft-Windows-SPB-ClassExtension` ETW provider:

```text
provider: {72CD9FF7-4AF8-4B89-AEDE-5F26FDA13567}
keyword:  0x8000000000000000
```

The sequence was:

```powershell
logman start sp11-spb-restart -ets `
  -p '{72CD9FF7-4AF8-4B89-AEDE-5F26FDA13567}' `
  0x8000000000000000 0xff `
  -o sp11-spb-restart.etl

pnputil /restart-device 'ACPI\MSHW0485\2&DABA3FF&0'

# after the post-restart observation window
logman stop sp11-spb-restart -ets
tracerpt sp11-spb-restart.etl -o sp11-spb-restart.csv -of CSV -y
```

The native `tracerpt` CSV retains the SPB payload bytes. The repository's
existing `tools/analyze_spb_etw_csv.py` and `tools/analyze_spb_cadence.py`
parsers consume it directly; WPA export is not required for this capture path.

## Evidence identity

The raw files are retained outside Git under the local evidence store and are
not redistributed by this repository:

```text
6b04530c04eb605e5b7a3c90e34e185e84fa64c21f4a387e1298992651062220  sp11-spb-restart.etl  10412032 bytes
a956e59638129c50f3b3a31e3307635194f4e2867aaf8e1dfea309a669917a42  sp11-spb-restart.csv  25668562 bytes
```

The converted CSV contains 43,016 lines.

## Payload summary

`tools/analyze_spb_etw_csv.py` reports:

```text
RX lengths:
      4 bytes: 1264
      8 bytes: 3
     20 bytes: 5
     28 bytes: 1
     64 bytes: 1
    124 bytes: 1
   1488 bytes: 1
   3636 bytes: 1241

Class-1 report IDs:
  report 0x12, 3636 bytes: 1241
  report 0x2e,   20 bytes: 1
  report 0x65,   20 bytes: 4
  report 0xa0,    8 bytes: 1
```

The returned HID report descriptor is again 1,484 bytes and exposes the same
ten top-level collections already documented by the project.

## Fresh restart chronology

The first-seen host `E2 00 20 00` operations are:

```text
SET_FEATURE 56 = ff ff ff ff ff ff 00
SET_POWER OFF
DEVICE_DESCRIPTOR request
REPORT_DESCRIPTOR request
GET_FEATURE 06
GET_FEATURE 60
GET_FEATURE 70
OUTPUT 65 = 00 00 ff a0 00 00 00 00 00 00 00 00 00 00 00 00
SET_FEATURE 70 = 01
OUTPUT 09 A1 (63 bytes)
SET_FEATURE 56 = bc e6 4a 2e 86 78 00
OUTPUT 09 A5 (63 bytes)
OUTPUT 65 = 01 00 ff a0 00 00 00 00 00 00 00 00 00 00 00 00
SET_FEATURE 05 = 01
OUTPUT 65 = 00 00 12 a0 89 14 00 3f ff ff ff ff 04 04 75 00
OUTPUT 65 = 02 00 ff a0 00 00 00 00 00 00 00 00 00 00 00 00
GET_FEATURE 73
```

This differs from both previously documented Windows restart/cold-attach
interleavings while remaining semantically consistent with them. In
particular, `GET_FEATURE 06` moves before the CFU/configuration work, one CFU
record occurs before `SET_FEATURE 0x70`, A1 precedes the report-`0x56` identity
write, and the remaining CFU records continue around the Heat/feedback owner.
That is additional live evidence for independent serialized collection owners,
not evidence for a new monolithic initialization sequence.

The installed-offer record contains byte 3 `0xa0`. This is not a new platform
constant: the already recovered `SurfaceCFUOverHid` constructor overwrites that
byte with the CFU token `0xa0`. The fresh trace therefore corroborates the
constructor model documented in `WINDOWS_CFU_BOUNDARY.md`.

The fresh A1/A5 records again contain the dynamic value `0x0190` in the fields
previously identified as provider-owned state. That matches the later July
captures and differs from the older SPB trace's `0x031a`, further ruling out a
fixed packet replay model.

## Cadence

`tools/analyze_spb_cadence.py` reports:

```text
Complete responses: 1258
Complete Heat responses: 1241
Header RX to body TX:
  n=1241 min=336.4 us p01=494.5 us median=531.7 us p99=790.7 us max=1082.8 us
Heat body RX to next Heat header TX:
  n=1240 min=5396.6 us p01=5822.2 us median=7791.3 us p99=9758.0 us max=2277496.4 us
Next-header gaps below 1 ms: 0
```

Only four header-to-body samples are below 490 us; the ten smallest are:

```text
336.4 350.4 393.6 431.2 491.8 491.9 493.1 493.7 493.7 493.8 us
```

Those isolated short samples do not justify changing the Phase 91
`usleep_range(490, 550)` guard. The fresh trace contains a restart and normal
Windows scheduling jitter, while Phase 91 uses the delay as a conservative
minimum before body service. The more important anti-overread invariant is
unchanged: Windows does not immediately request another response after a Heat
body.

## Separate Windows event-log observation

Recent System logs contain repeated Kernel-PnP event 219 warnings for
`HID\MSHW0485&Col06`, the firmware-update collection, where `WudfRd` reports
status `0xC0000365`. The base device and all currently present MSHW0485 child
collections nevertheless report `OK`, and no matching touch-input error was
found in the same focused query. Treat this as a CFU/UMDF-side observation,
not evidence of a current touchscreen failure.

## Evidence boundary and next lead

This was a controlled host-side PnP restart, not a natural panel-initiated
reset. It therefore does not close the remaining natural-reset lifecycle gap.
It does, however, make future Windows bus captures reproducible without KDNET
or WPA and reconfirms the one-byte `0x70` transaction on the current Windows
stack.

The highest-value next protocol question remains the same: identify the owner
and semantic connection, if any, between HID Feature `0x70` and the firmware's
`PRE_OS` versus `Normal (Full Frame)` report modes. Separately, a low-overhead
reset-only capture is still needed to observe one genuine panel-initiated reset.
