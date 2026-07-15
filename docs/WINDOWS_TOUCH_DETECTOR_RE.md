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

When calibration is enabled, `FUN_18008f058` performs the following operation
for each raw byte:

```text
calibrated = clamp(offset + gain * raw, 0, 255)
```

The captured SP11 corpus is consistent with identity calibration, but the
report/configuration field that proves the runtime gain and offset has not yet
been recovered. Linux therefore consumes the panel byte grid directly and
keeps this assumption explicit.

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
record format observed in all 1,381 captured frames is:

```text
u8 type; u8 flags; u16 payload_length; u8 payload[payload_length];
```

The stable record types are `0x00`, `0x03`, `0x04`, `0x07`, `0x0b`, `0x32`,
and `0xff`. Windows parses these records before detection, but the handler
table and the exact detector fields populated by each record are not yet fully
named. Phase 57 does not invent semantics for them.

## Deliberate remaining fallbacks

This is a faithful port of the first candidate-extraction stage, not a source-
equivalent replacement for the whole proprietary library. Windows still has:

- track lifecycle, matching, and motion prediction;
- weak-blob/NSR classification after initial candidate creation;
- edge compensation and configuration-dependent coordinate transforms;
- pen-driven palm rejection.

Linux currently uses `input_mt_assign_slots`, bounded coordinate smoothing,
a six-frame missing-contact hold, and conservative size/span rejection for
those later stages. Those fallbacks remain isolated and documented rather
than being described as Windows algorithms.

## Offline validation

The Phase 57 Python mirror and kernel policy share the same constants. The
captured Windows corpus at
`/home/geoca/sp11-touch-captures/etw_3636_frames_20260506` produces:

```text
frames=1381 decoded=1381 errors=0
contact_frames=1113 idle_frames=268 palm_rejections=0
small_strong=0 weak_rejections=6
contacts_per_frame=0:268,1:1113
```

The matched ARM64 module set builds successfully for
`7.1.1-sp11-gpicmp1+`. Hardware loading is intentionally a separate step.
