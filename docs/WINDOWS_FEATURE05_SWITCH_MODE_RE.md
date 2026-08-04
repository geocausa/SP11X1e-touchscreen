# Windows Feature 0x05 switch-mode reverse engineering

## Result

The installed Windows Surface touch stack identifies HID Feature report `0x05`
as **Switch Mode Feedback** for the raw-Heat/feedback collection.  The Windows
producer resolves vendor Usage Page `0xff00`, Usage `0xc8` from the live HID
descriptor, constructs the two-byte report buffer `{0x05, 0x01}`, and sends it
through the Heat interface during normal `InitializeHeatProcessor` bring-up.

This substantially narrows the remaining PRE_OS/full-frame question.  The
shipped panel firmware independently exposes engineering command
`SetReportMode`, whose values are `0 = PRE_OS` and `1 = Normal (Full Frame)`.
A fresh Windows SPB restart capture shows `SET_FEATURE 0x05 = 01` followed
163.965 ms later by the first new 3,636-byte Heat frame and then continuous
full-frame traffic.  The previous Heat frame was 2.114 s earlier, before the
re-enumeration interval.

The host-side and firmware-side semantics therefore agree strongly, making
Feature `0x05 = 01` the best evidenced production-HID bridge to normal
full-frame operation.  The final panel-side table-driven HID consumer has not
yet been recovered, so this document does **not** claim that Feature `0x05`
directly invokes engineering CLI command 107 or that the two command namespaces
are identical.

## Evidence identities

The Windows processing binary is the same image used by the existing static
analysis:

```text
TouchPenProcessor0C83.dll
version: 26.6.139.0
size:    9,504,272 bytes
sha256:  615a28136f14678298dcd9f009c9295456a9e7ce878717b58d371d343b4c7132
```

It is loaded by `ISM.exe` together with `HeatCore.dll`.  The extension INF for
`HID\MSHW0485&Col02` explicitly installs it as the Heat software processor:

```text
HKR,Heat,SoftwareProcessor,REG_SZ,"%13%\TouchPenProcessor0C83.dll"
```

The matching installed firmware package remains:

```text
SurfaceTouchG6_FW_MSHW0485.payload.bin
container sha256: addfa77b768e0905010766e73117872bc2feddbc8ee9f080322767456e82f1e5
unwrapped sha256: 281c299afccbb02275f972d6c409b950784cb3859c6bed3ef08aeb3083fd139e
ARC sha256:       319ec4279a6b1922e33da8878c5c56639d5a059642583c6ee4b5a0002d736d48
```

The August 4 SPB restart evidence remains outside Git:

```text
6b04530c04eb605e5b7a3c90e34e185e84fa64c21f4a387e1298992651062220  sp11-spb-restart.etl
a956e59638129c50f3b3a31e3307635194f4e2867aaf8e1dfea309a669917a42  sp11-spb-restart.csv
```

## HID descriptor identity

The exact 1,484-byte descriptor in the live capture and installed firmware
contains Feature report `0x05` as one eight-bit vendor feature:

```text
Report ID:  0x05
Usage Page: 0xff00
Usage:      0x00c8
Report size:  8 bits
Report count: 1
Feature flags: 0x02
```

The adjacent Windows feedback output report `0x09` uses the same vendor page
and Usage `0xc9`.  That neighboring pair is useful because both are resolved by
the same Windows HID usage resolver rather than by hard-coded report IDs.

## Windows producer

The generic HID usage resolver is at `0x180060ac8`.  Its known report-`0x09`
caller passes:

```text
page  = 0xff00
usage = 0x00c9
class = 0
```

The Feature-`0x05` path at `0x180062698` passes:

```text
page  = 0xff00
usage = 0x00c8
class = 1
output report-id storage = FeedbackManager + 0xa8
```

The binary's own diagnostic strings identify this function as the switch-mode
path:

```text
FeedbackSendSwitchModeFeedbackEntry
FeedbacksDisabledSendSwitchModeFeedback
SendSwitchModeFeedback_HidDescriptorFailed
SendSwitchModeFeedback
```

After the descriptor lookup succeeds, the function performs the equivalent of:

```text
resolve_feature_report(0xff00, 0x00c8, &manager->buffer[0]);
manager->buffer[1] = 1;
send_feature(manager->buffer, ...);
```

The first byte is therefore descriptor-derived; on this panel it is report ID
`0x05`.  The value byte is explicitly written as `1`.  This is stronger than a
captured packet replay: Windows independently reconstructs `{0x05, 0x01}` from
HID identity plus a fixed switch-mode value.

## HeatCore framework proof

Microsoft's generic HEAT framework independently assigns the same HID field a
reporting-mode meaning.  The installed binary is:

```text
C:\Windows\System32\HeatCore.dll
file version: 10.0.26100.8737
length:       396800
SHA-256:      b5518a12e1891b1bbb5aef2b5852a653e03ad7536a3c60f53246dd34a933f169
file description: Microsoft (R) Windows HEAT processor framework
```

The matching Microsoft public symbols are reproducible from the PE's embedded
CodeView identity:

```text
PDB:        HeatCore.pdb
GUID:       c9d4046b-b9dc-bb39-c411-95272067deca
age:        1
symbol key: C9D4046BB9DCBB39C41195272067DECA1
PDB size:   921600
PDB sha256: f3d0134e85e2ae44f4e125d0aea4d6ef3dd4f8579332cf4942d2cd7dfe034924
```

The PDB was retrieved from Microsoft's public symbol server and is retained
with the private capture evidence, not committed to Git.  It names the relevant
functions at their current image addresses, including
`HIDDeviceInterface::SetHeatReportingMode` (`0x18000fea0`),
`CapImg::Protocol::HID::BuildFeatureReportForModeSwitch` (`0x180013dc8`),
`HeatDevice::DeinitializeHardware` (`0x18002ffe0`),
`HeatDevice::InitializeHardware` (`0x180030920`),
`HeatDevice::ResetHardware` (`0x180030e30`), and
`HeatDevice::SetProcessorLoaded` (`0x180031000`).

The live `ISM.exe` process loads `HeatCore.dll` and is itself a child of
`dwm.exe`.  This matches `heat.inf`, which binds `HID_DEVICE_UP:000D_U:000F`,
creates the `Heat\VendorSpecific` registry subtree, and explicitly grants the
DWM user group access to the HEAT collection.

`HeatCore.dll` contains the internal identifiers:

```text
CapImg::Protocol::HID::BuildFeatureReportForModeSwitch
HIDDeviceInterface::SetHeatReportingMode
CapImg::Protocol::HID::UpdateFrameDataTransferForReport
HeatDevice_ReportingModeSwitchSent
ReportingMode
ModeSwitchSupported
```

The mode-switch builder at `0x180013dc8`, called by
`HIDDeviceInterface::SetHeatReportingMode` at `0x18000fea0`, writes the
report-ID byte into the output buffer and then calls the imported HID parser
API `HidP_SetUsageValue`.  On the live descriptor the effective call is:

```text
ReportType      = HidP_Feature (2)
UsagePage       = 0xff00
LinkCollection  = 0
Usage           = 0x00c8
UsageValue      = reporting mode
PreparsedData   = device HID preparsed data
Report          = buffer beginning with report ID 0x05
ReportLength    = descriptor-derived report length
```

Thus the generic framework does not treat byte `01` as an opaque vendor token:
it explicitly sets the descriptor field `0xff00:0x00c8` to the requested
reporting-mode value.  Because that field is the sole eight-bit Feature field
in report `0x05`, the live device resolves the operation to `{0x05, mode}`.

The HEAT hardware lifecycle fixes the meaning of the two observed values.  The
same virtual `SetHeatReportingMode` slot is reached as follows:

```text
DeinitializeHardware     -> mode 0
ResetHardware            -> mode 1
SetProcessorLoaded(true) -> mode 1, when reporting is not already enabled
monitor-power-on resume  -> mode 1, when an off transition was pending and reporting was active
```

PDB-assisted decompilation is important here because one diagnostic string is
slightly misleading.  `HeatDevice::InitializeHardware` itself only queries the
hardware properties (with one bounded retry), registers a
`GUID_MONITOR_POWER_ON` notification, and returns.  The string
`InitializeHardware: Failed to enable Heat reporting mode.` is emitted from
`HeatDevice::SetProcessorLoaded(bool)`, where a transition to `true` calls the
mode interface with value `1` and then marks reporting enabled.  Thus the
message text must not be treated as the owning function name.

The other diagnostics line up directly with their lifecycle owners:

```text
DeinitializeHardware: Failed to disable Heat reporting mode.
ResetHardware: Failed to enable Heat reporting mode.
```

The monitor-power callback does not send mode `0` when the display turns off.
It records the off transition and, when the monitor turns back on, reissues mode
`1` if HEAT reporting was already active.

This independently proves that `0xff00:0x00c8 = 1` means **enable HEAT
reporting mode**, while value `0` means **disable HEAT reporting mode**.  It
strengthens the TouchPenProcessor `Switch Mode Feedback` result without
requiring a live process-memory patch, an experimental report value, or a
firmware command replay.

It still does not prove that the panel-side HID handler literally dispatches to
engineering CLI command 107.  The remaining proof boundary is now entirely on
the panel side: connect production HID usage `0xff00:0x00c8` to the firmware's
internal report-mode state or generic HID Feature consumer.

## Feedback-manager gate

The switch sender first checks processor state byte `+0x262`.  Dedicated tiny
setters at `0x180060948` and `0x180060a08` clear and set that byte.  Their
associated binary strings are `FeedbacksDisabled` and `FeedbacksEnabled`,
respectively, establishing the state meaning.

`FeedbackManager_Init` at `0x180060e30` enables that state only when a global
processor configuration byte at offset `+0x790` equals `1`.  A neighboring
configuration byte at `+0x791` is copied into a separate manager flag.  This
shows the Feature-`0x05` path is configuration/lifecycle driven; it is not a
fixed delay accidentally observed in one trace.

The protected live `ISM.exe` process denied ordinary `OpenProcess` memory reads,
so the runtime config bytes were not dumped and Windows process protections were
not weakened.

## InitializeHeatProcessor call chain

`SendSwitchModeFeedback` has exactly one direct static caller in the normal
initialization path.  The caller:

1. initializes the FeedbackManager;
2. checks a boolean initialization argument;
3. when that argument equals `1`, calls `SendSwitchModeFeedback`;
4. continues Heat/reporter initialization.

One normal caller of this helper hard-codes that boolean argument to `1` before
calling it.  A later re-initialization path propagates a runtime flag instead.
This proves the switch is intentional normal bring-up behavior rather than a
CFU, debugger, or exceptional recovery artifact.

## Fresh SPB chronology

The native `logman`/`tracerpt` restart capture contains one logical write:

```text
SET_FEATURE 0x05 = 01
```

Relative to that write:

```text
previous Heat body:  -2114.142 ms
first new Heat body:  +163.965 ms
next Heat body:       +172.142 ms
next Heat body:       +180.574 ms
next Heat body:       +190.792 ms
```

The first post-switch Heat body is report `0x12`, 3,636 bytes.  Continuous
roughly 8--10 ms full-frame delivery follows.  Several bounded attach/CFU
responses still interleave before the first Heat frame, so the 163.965 ms value
is an observed lifecycle interval, not a proposed Linux sleep constant.

## Firmware-side semantic match

The installed firmware's `GenericCliDescriptor.xml` independently declares:

```text
Command 107: SetReportMode
Mode 0: PRE_OS
Mode 1: Normal (Full Frame)
```

The production Windows host calls its Feature-`0x05` producer
`SendSwitchModeFeedback`, hard-codes the value `1`, and Heat full-frame traffic
starts immediately afterward in the observed attach chronology.  These facts
make a common report-mode state the strongest current interpretation.

However, the firmware resource CLI and production HID transport are separate
interfaces.  Existing ARC analysis shows that the HID descriptor is enumerated
from a tag/length resource container and the production consumer is likely
generic/table-driven.  No direct ARC code edge from HID Usage `0xc8` to CLI
command 107 has yet been recovered.  Therefore the precise statement is:

> Windows Feature `0x05 = 01` is Switch Mode Feedback and operationally admits
> normal raw-Heat streaming; it is strongly consistent with selecting the
> firmware's Normal (Full Frame) report mode, but the panel-side production-HID
> handler still needs to be connected to the firmware report-mode state.

## Consequences for Linux

- Feature `0x70` is no longer a report-mode candidate; its owner is Slim Pen
  auto-bonding configuration.
- Feature `0x05` is now the evidence-backed mode-switch candidate and already
  exists in the Windows-parity chronology.
- Do not replace Phase 91's hardware-validated sequence or timing merely to make
  it look more literal.  This result explains ownership and semantics; it does
  not invalidate the stable production control.
- Do not issue engineering CLI command 107 from Linux.  Its existence is static
  semantic corroboration, not evidence that the engineering interface belongs
  in the production driver.
- The useful remaining static target is the ARC generic HID Feature dispatcher
  or the underlying report-mode state variable, not further literal searches
  for report ID `0x05`.
