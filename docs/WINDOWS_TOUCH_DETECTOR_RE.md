# Windows touch detector reverse engineering

This note records the facts used by the Phase 57 detector port. The source is
`TouchPenProcessor0C83.dll` from the Surface Pro 11 Windows installation,
analysed as an ARM64 PE at image base `0x180000000`.

## Confirmed call path

The heat processor obtains sections `0x0100` and `0xff00`, decodes the sparse
68 by 46 byte grid, and passes it into the detector:

```text
SurfaceHeatProcessor::ProcessHeatmap
  FUN_180090b88
    FUN_18008f058        sparse-grid decode and calibration
    FUN_18008f828        metadata parser and detector dispatch
      FUN_18004ade0
        FUN_18004ab08    diagnostic injection only
        FUN_18004b060
          FUN_180046b10  detector/tracker pipeline
            FUN_180040b58
              FUN_180047a98  threshold and scan-line labelling
              FUN_180045d98  label union and candidate admission
```

`SurfaceHeatProcessor::SanitizeHeatmap` at `0x180009820` is a stub returning
success. It does not compute a frame MAD or another adaptive noise floor.

For the alternate 16-bit sparse encoding, `FUN_18008f058` can perform the
following operation before clamping to a byte:

```text
calibrated = clamp(offset + gain * raw, 0, 255)
```

The configuration provenance is now exact. `FUN_18008d2d8` points the parser
at selected PSDB record `+0x784`; its enable byte is `+0x7a0`, gain is the
float at `+0x798`, and offset is the float at `+0x79c`. Project 0x0c83 stores
zero for all three, so its 16-bit conversion is disabled. More importantly,
all 1,381 captured SP11 Heat sections use mode one with eight-bit elements.
That branch copies every sample byte directly and never reads the calibration
record. Linux's byte grid is therefore exact for the observed Windows path,
not an assumed identity calibration. `HeatCalibrationPolicy.from_dll` keeps
the unused 16-bit branch reproducible without applying it to byte reports.

## Candidate extraction

`FUN_180047a98` computes an absolute byte ceiling rather than subtracting a
per-frame modal baseline:

```text
active_max = round(((1.0 - configured_threshold) - 0.6) / 0.0022203543)
```

The panel's observed idle level is 180 or 181. The inferred normal
configuration gives an active ceiling of 171. The DLL uses a linear lookup
whose zero crossing is approximately byte 180, so integer weight `180 - raw`
is the bounded kernel equivalent used for centroids.

The DLL's scan-line labeller joins edge-adjacent cells. Diagonally touching
cells do not form one candidate. `FUN_180045d98` admits a candidate when it
contains at least three cells. A one- or two-cell candidate can also survive
when its peak passes a second, stronger configured threshold. The current
panel-specific approximation for that threshold is raw byte 162.

These rules replace the earlier guessed modal-delta threshold, five-pixel
minimum, and total-strength minimum. The fixed ceiling and strong-candidate
ceiling are printed in the driver's `state` attribute so hardware results can
be compared without rebuilding.

## Metadata section

Section `0xff00` is a nested TLV stream, not a ready-made contact list. The
Windows dispatcher starts at byte seven of the section, so the outer header's
`header_value` byte is also the first nested record type. The record format
observed in all 1,381 captured frames is:

```text
u8 type; u8 flags; u16 payload_length; u8 payload[payload_length];
```

The stable record types are `0x00`, `0x03`, `0x04`, `0x07`, `0x0b`, `0x32`,
and `0xff`. `FUN_180068670` dispatches them through the handler table built by
`FUN_180067128`.

The semantics of type `0x04` are now exact. `FUN_180069690` reads a count byte
and up to sixteen little-endian `u16` values at payload offsets `4 + i * 4`.
Those firmware-provided values are copied into the detector frame fields later
read by `FUN_18003c048`. That filter:

1. rounds the candidate's preserved raw sensor-row coordinate;
2. maps the 46 rows through the project-0x0c83 46-to-16 lookup table;
3. rejects only when the selected firmware value is strictly greater than the
   embedded profile cutoff of 655.

The exact row mapping is `0..15, 0..15, 2..15`. All 23 embedded project
profiles contain the same cutoff. Every captured SP11 frame has 16 values,
and the entire corpus contains only values 0, 1, and 2. This classifier is
therefore a behavioral no-op for the available captures, but Linux now parses,
validates, applies, and reports it for Windows fidelity and future evidence.
Malformed or duplicate type-`0x04` records fail the frame safely; a missing
record leaves the optional filter disabled.

Two additional context-byte handlers are now structurally exact. Type `0x07`
requires a four-byte payload and copies payload byte one to internal sensor
frame `+0xd8eb`, which becomes tracker frame `+0xb771` after the caller's
`+0x217a` object shift. Type `0x94` contains counted subrecords; subtype zero
updates a zero-initialized process-global byte which is copied to internal
`+0xd964` / tracker `+0xb7ea` every frame and persists when later frames omit
type `0x94`.

All 1,381 captured frames contain type `0x07` payload `00 00 00 00`, none
contains type `0x94`, and both tracker context sources are therefore zero in
the saved session. The decoder and corpus regression model and report this
without assigning an unproven human-facing meaning to either byte. Other
metadata record semantics are not yet fully named; Linux does not invent
behavior for them.

## Deliberate remaining fallbacks

This is a faithful port of the first candidate-extraction stage, not yet the
coherent kernel replacement for the whole proprietary library. The deployed
Linux baseline still substitutes for later Windows stages with:

- `input_mt_assign_slots` plus a logical-space association gate;
- fitted confirmation, missing-track, and coordinate-smoothing windows;
- conservative size/span palm rejection; and
- no pen-driven palm branch, by operator choice.

Phase 69 now represents Windows assignment geometry, classification history,
finger lifecycle, expanded centroid, output construction, and duplicate merge
offline. Those pieces remain out of the live module until they can replace the
fallbacks as one frame-ordered change.

## Offline validation

The Phase 57 Python mirror and kernel policy share the same constants. The
captured Windows corpus at
`/home/geoca/sp11-touch-captures/etw_3636_frames_20260506` produces:

```text
frames=1381 decoded=1381 errors=0
contact_frames=1113 idle_frames=268 palm_rejections=0
small_strong=0 weak_rejections=6
nsr_metadata_frames=1381 nsr_rejections=0 nsr_cutoff=655 nsr_value_max=2
contacts_per_frame=0:268,1:1113
```

The matched ARM64 module set builds successfully for
`7.1.1-sp11-gpicmp1+`. Hardware loading is intentionally a separate step.
