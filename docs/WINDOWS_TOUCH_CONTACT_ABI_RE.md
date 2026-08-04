# Windows HEAT touch-contact ABI reverse engineering

This note records the recovered Windows finger-touch output semantics around
contact geometry.  It separates the processor's internal component/track
records from HeatCore's public Touch HID injection layout.

The main conclusions are:

- Windows HEAT **Touch does not expose Pressure** as a supported Touch
  capability;
- Windows HEAT **does expose Geometry**, represented by 32-bit Width and Height
  fields in the generated Touch HID report;
- the Surface processor derives raw contact dimensions from the inclusive
  component bounds as `max - min + 1` in each sensor axis;
- those raw dimensions may be temporally smoothed in the per-track state before
  later output processing.

This is static reverse-engineering evidence from the exact installed
`TouchPenProcessor0C83.dll` and `HeatCore.dll`.  It does not change the Phase 91
Linux production baseline.

## Exact binaries

Processor:

```text
TouchPenProcessor0C83.dll
version 26.6.139.0
SHA-256 615A28136F14678298DCD9F009C9295456A9E7CE878717B58D371D343B4C7132
```

Heat framework:

```text
C:\Windows\System32\HeatCore.dll
version 10.0.26100.8737
SHA-256 b5518a12e1891b1bbb5aef2b5852a653e03ad7536a3c60f53246dd34a933f169
```

The matching public `HeatCore.pdb` supplies useful function names.  The exact
processor CodeView record names `TouchPenProcessor.pdb` with GUID/age:

```text
9F71B5E9-29AC-14FD-B05C-74DB124BB8F7 / 1
```

The exact Microsoft symbol-server path returns HTTP 404, so the processor PDB
is not available there and its private structures remain anonymous.

## Touch capability boundary: Pressure versus Geometry

Direct decompilation of HeatCore's pointer-capability declaration path shows
that Touch accepts the ordinary touch state/position fields and Geometry, while
the following group is explicitly rejected for Touch:

```text
Invert
Eraser
Barrel
Pressure
Twist
Tilt
PenId
```

The same code treats Geometry as unsupported for Pen, demonstrating that these
checks are pointer-class-specific rather than a claim that HeatCore has no
pressure support anywhere.

For Surface finger-touch parity this makes `ABS_MT_PRESSURE` the wrong default
target.  A private processor scalar or force-like channel should not be renamed
"pressure" without independent evidence.

Geometry is different: it is a real Touch capability and controls whether the
Touch HID descriptor publishes Width and Height.

## Generated Touch HID descriptor

HeatCore function:

```text
Touch::GenerateHidDescriptor(...)
VA 0x180011df8
```

builds the HID descriptor from fixed fragments and capability-controlled
fragments.

The Touch descriptor contains the standard Digitizer Touch Screen/Finger
structure with:

- Report ID 1;
- Contact Count;
- optional Scan Time;
- Tip Switch;
- optional Confidence;
- optional In Range;
- Contact Identifier;
- X and Y;
- Geometry-controlled Width and Height.

The Geometry capability is bit 5 in the recovered capability mask.

When Geometry is disabled, HeatCore emits one X and one Y plus constant padding
in place of the extra geometry slots.  When Geometry is enabled, the relevant
fragments are:

```text
Usage X      Report Size 32  Report Count 2
Usage Width  Report Size 32  Report Count 1
Usage Y      Report Size 32  Report Count 2
Usage Height Report Size 32  Report Count 1
```

The fixed contact-report geometry order is therefore:

```text
X1, X2, Width, Y1, Y2, Height
```

all as 32-bit fields.

## HeatCore `CONTACT_REPORT`

HeatCore function:

```text
Touch::ConvertHeatContact(HeatContact *, Touch::CONTACT_REPORT *)
VA 0x180011d90
```

zeroes a 0x21-byte destination and copies fields from an internal `HeatContact`.
The geometry portion is:

| `CONTACT_REPORT` offset | meaning | `HeatContact` source |
|---:|---|---:|
| `+0x03` | X1 | `+0x13` |
| `+0x07` | X2 | `+0x23` |
| `+0x0b` | Width | `+0x2b` |
| `+0x0f` | Y1 | `+0x17` |
| `+0x13` | Y2 | `+0x27` |
| `+0x17` | Height | `+0x2f` |

The earlier bytes carry contact flags and Contact ID.  Later optional fields
remain separate from Width/Height and should not be labelled without their own
capability proof.

## `HeatTouchContactNew` source layout

The matching HeatCore PDB names:

```text
HeatPointerInputReporter::ReportTouchContactFrame(
    HeatTouchContactNew *, uint, ushort)
```

at VA `0x1800318d0`.

Its copy loop consumes 0x20-byte source records.  Combining that copy with
`Touch::ConvertHeatContact` and the generated HID descriptor gives the source
geometry layout:

| `HeatTouchContactNew` offset | meaning |
|---:|---|
| `+0x00` | Contact ID (`u16`) |
| `+0x02` | contact-state flags (`u16`) |
| `+0x04` | X1 (`u32`) |
| `+0x08` | Y1 (`u32`) |
| `+0x0c` | X2 (`u32`) |
| `+0x10` | Y2 (`u32`) |
| `+0x14` | **Width (`u32`)** |
| `+0x18` | **Height (`u32`)** |
| `+0x1c` | later optional field (`u16`, semantics not assigned here) |

The reporter duplicates the position pairs into its internal `HeatContact`
representation before `Touch::ConvertHeatContact` selects the fields used by
the HID report.

## Processor component bounds

The already recovered processor 0x38-byte contact/candidate record retains:

```text
+0x18 min_x   u16
+0x1a min_y   u16
+0x1c max_x   u16
+0x1e max_y   u16
+0x20 point count
```

Normal output records preserve the component bounds.  Split records use clipped
one-cell bounds, which is consistent with shape being a first-class component
property rather than reconstructed from only the final centroid.

## Raw Width/Height formula

A structure-aware ARM64 scan located the track-update path at
`0x18004b318`.  Its disassembly reads all four component bounds together and
computes:

```text
raw_width  = max_x - min_x + 1
raw_height = max_y - min_y + 1
```

The relevant instruction sequence is equivalent to:

```text
ldrh max_x, [candidate, #0x1c]
ldrh min_x, [candidate, #0x18]
sub  width, max_x, min_x
add  width, width, #1

ldrh max_y, [candidate, #0x1e]
ldrh min_y, [candidate, #0x1a]
sub  height, max_y, min_y
add  height, height, #1
```

Both values are converted to float and stored in per-track dimension fields.
A second track-initialization/update path at `0x18004c0c8` independently uses
the same inclusive-bound formula.

## Dimension smoothing

The `0x18004b318` path also proves that raw geometry is not always used
unchanged.

A profile/state object contains:

- a Boolean enabling dimension filtering;
- a floating-point blend weight.

When filtering is enabled, the processor computes the new track dimensions as
an affine blend of the previous track dimensions and the current raw
`max-min+1` dimensions.  In conceptual form:

```text
new_width  = raw_width  * alpha + old_width  * (1 - alpha)
new_height = raw_height * alpha + old_height * (1 - alpha)
```

When the filter is disabled, the track receives the current raw dimensions
directly.

This is important for Linux parity: copying instantaneous bounding-box width and
height is a useful first implementation, but it is not necessarily the exact
Windows per-frame geometry when this profile-controlled smoothing is active.

## Remaining processor-side boundary

The following chain is now proven on both sides:

```text
component bounds
    -> raw width/height = inclusive extents
    -> optional per-track smoothing
    -> processor output pipeline
    -> HeatTouchContactNew Width/Height
    -> HeatCore CONTACT_REPORT Width/Height
    -> generated HID Touch Width/Height usages
```

The only still-anonymous static link is the exact private processor adapter that
copies the smoothed per-track dimension fields into
`HeatTouchContactNew +0x14/+0x18`.  The public processor PDB is unavailable, so
that final private helper currently lacks a trustworthy symbol/type name.

The semantic uncertainty is nevertheless much smaller than before: there is no
remaining ambiguity about what Windows exposes publicly, what raw geometric
quantity the processor computes, or the existence of optional track-level
smoothing.

## Linux implication

Phase 91 currently publishes MT X/Y only.  A future experimental shape patch
should therefore focus on:

```text
ABS_MT_TOUCH_MAJOR
ABS_MT_TOUCH_MINOR
```

(and orientation only after a clear Linux-unit mapping is chosen), not on
finger `ABS_MT_PRESSURE`.

Before promoting shape fields into the production baseline, validate:

1. sensor-cell extents versus Windows Width/Height units;
2. whether the active Surface profile enables the recovered width/height
   smoothing and with what weight;
3. labelled small/large/fingertip/edge contacts;
4. split/merged contacts, where the component bounds intentionally change.
