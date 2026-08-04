# Windows Feature `0x70`: pen auto-bonding capability

## Result

HID Feature report `0x70` is not the touchscreen PRE_OS/full-frame report-mode
selector.  On the tested Surface Pro 11 OLED, Microsoft's installed
`SurfacePenBleLcAddrAdaptationDriver.sys` identifies report `0x70` as
`FEATURE_REPORT_ID_HOST_AB_CAPABILITY` and handles it as part of the Slim Pen
auto-bonding path.

The live HID descriptor and the Microsoft driver independently identify the
one-byte report layout:

```text
bit 0  vendor page 0xfff4 usage 0x10  HOST_HW_AUTO_BONDING_CAPABILITY
bit 1  vendor page 0xfff4 usage 0x22  SURFACE_OOB_HW_AUTO_BONDING_CAPABILITY
bit 2..7                            constant padding
```

The fresh Windows SPB restart capture therefore has a direct semantic
interpretation:

```text
GET_FEATURE 0x70 response = 02
    host_hw_auto_bonding        = 0
    surface_oob_hw_auto_bonding = 1

SET_FEATURE 0x70 = 01
    host_hw_auto_bonding        = 1
    surface_oob_hw_auto_bonding = 0
```

The observed `02 -> 01` exchange is an auto-bonding capability/control
handshake.  It is not evidence that report `0x70` selects normal Heat/full-frame
operation.

## Evidence identity

The installed owner binary is:

```text
C:\Windows\System32\DriverStore\FileRepository\
surfacepenblelcaddradaptationdriver.inf_arm64_32a250a9b74262f2\
SurfacePenBleLcAddrAdaptationDriver.sys

file version: 3.55.3.0
length:       322048
SHA-256:      3d1f2ee6a4dd143fb1e2129e84f93aea164f1377fd213c9a52f027ff80f1bd4c
```

It is bound to the live `MSHW0485` child containing the vendor configuration
reports:

```text
HID\MSHW0485&COL05\3&3B13A23&0&0004
service: SurfacePenBleLcAddrAdaptationDriver
```

The matching top-level HID collection is vendor page `0xfff4`, usage `0x0001`,
with reports `0x54`, `0x55`, `0x56`, `0x6e`, `0x6f`, `0x70`, and `0x73`.

The fresh SPB evidence and hashes are recorded in
[WINDOWS_SPB_20260804_LIVE_RESTART.md](WINDOWS_SPB_20260804_LIVE_RESTART.md).
The raw ETL/CSV and Ghidra project remain outside Git.

## Descriptor proof

The 1,484-byte report descriptor returned by the live panel declares three
Feature fields under report ID `0x70`:

```text
Feature page=0xfff4 usage=0x10 size=1 count=1 Data,Var,Abs
Feature page=0xfff4 usage=0x22 size=1 count=1 Data,Var,Abs
Feature                         size=6 count=1 Const,Array,Abs
```

Thus the logical report content is exactly one byte.  The remaining six bits
are padding, not additional undocumented payload bytes.

This independently validates the corrected Windows transfer boundary used in
[PHASE72_KDNET_ERRATUM.md](PHASE72_KDNET_ERRATUM.md) and
[PHASE82_SET70_LENGTH.md](PHASE82_SET70_LENGTH.md).

## Microsoft driver proof

Ghidra 12.1.2 analysis of the installed ARM64 driver reaches the report through
`PenEvtIoDeviceControl` in `Queue.c`.

For `IOCTL_HID_GET_FEATURE`, report ID `0x70` is accompanied by the diagnostic
string:

```text
PenEvtIoDeviceControl.FEATURE_REPORT_ID_HOST_AB_CAPABILITY
[G6Touch]{PenService queries AutoBonding}
```

For `IOCTL_HID_SET_FEATURE`, the same report ID is accompanied by:

```text
PenEvtIoDeviceControl.FEATURE_REPORT_ID_HOST_AB_CAPABILITY
[G6Touch]{PenService enables Auto Bonding}
```

The set-feature parser `FUN_14002d4c8` asks the HID parser for vendor page
`0xfff4`, usage `0x10`, and labels it:

```text
USAGE_HOST_HW_AUTO_BONDING_CAPABILITY
```

It obtains the Boolean value through `HidP_GetData` and retains that value in
the driver's device state.  This is direct handler-level evidence, not an
inference from packet timing.

A separate upward-processing path, `FUN_1400053d0`, parses vendor-page usages
returned from the device.  When it finds usage `0x22`, the driver logs:

```text
USAGE_SURFACE_OOB_HW_AUTO_BONDING_CAPABILITY
{Use HW with MPP 2.6 support}
```

and calls `HidP_SetUsages` for usage `0x10`.  Nearby diagnostics distinguish
hardware with and without the auto-bonding capability and explicitly mention
Slim Pen 2 versus Slim Pen 1 / MPP 2.5 hardware.

The same code family identifies device-side usages:

```text
0x12  USAGE_DEVICE_AUTO_BONDING_CAPABILITY  {Use Slim Pen 2}
0x11  USAGE_DEVICE_KNOWN_HOST               {Use a previously auto bonded Slim Pen 2}
```

Together these names and call paths place report `0x70` firmly in the Surface
pen/Bluetooth auto-bonding architecture.

## Consequences for the Linux driver

This closes the former hypothesis that Feature `0x70` might be the HID bridge
to firmware engineering CLI command 107 (`PRE_OS` versus `Normal (Full
Frame)`).  Those are separate mechanisms.

It also changes how the historical experiments should be interpreted:

- Phase 72's two-byte `SET_FEATURE 0x70 = {01,02}` was not a faithful Windows
  report and its apparent benefit cannot be attributed to selecting full-frame
  mode.
- Phase 82 correctly reduced the logical report to Windows' one-byte `{01}`.
  Its noisy startup does not make the second Phase 72 byte meaningful; it shows
  that the reset behavior remained coupled to other initialization/recovery
  variables.
- Phase 91 should remain unchanged as the hardware-proven control.  This
  reverse-engineering result alone is not a reason to modify a stable
  production boot image.
- Because Linux currently has no pen auto-bonding implementation, future
  isolation can test whether report `0x70` can be omitted from a touch-only
  initialization path.  That must be a one-variable, one-shot experiment and
  must not be folded directly into Phase 91.

The real full-frame selector remains unresolved.  The next search should focus
on the Heat/feedback activation owner and its other configuration traffic,
including `SET_FEATURE 0x05 = 01`, rather than continuing to assign report-mode
semantics to `0x70`.

## Reproducibility boundary

No Microsoft binary is committed.  The binary hash, device binding, report
layout, function-level behavior, diagnostic identifiers, and live bus values
are sufficient to reproduce this finding on a locally installed matching
Windows stack.

`tools/windows_device_config.py` contains a small independent decoder for the
one-byte report and rejects non-zero descriptor padding bits.  The decoder does
not communicate with hardware or replay any report.
