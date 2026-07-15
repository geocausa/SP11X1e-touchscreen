# Phase 59 firmware NSR metadata

Phase 59 ports one more exact, bounded stage from the Windows
`TouchPenProcessor0C83.dll`: the firmware-supplied NSR-bin gate applied after
initial heat-blob extraction. It does not guess a new threshold and does not
alter the transport, tracker, live installation, or boot configuration.

## Recovered Windows path

- `FUN_180068670`: parses section `0xff00` as nested records starting at
  section byte seven.
- `FUN_180067128`: constructs the nested-record handler table.
- `FUN_180069690`: handles record type `0x04` and stores its count and values.
- `FUN_18003bdf0`: preserves the raw candidate Y coordinate used for bin
  selection.
- `FUN_18003c240`: copies the project-profile cutoff into the live detector.
- `FUN_18003c048`: maps the rounded sensor row to a bin and rejects when its
  firmware value exceeds the cutoff.

The type-`0x04` payload is:

```text
u8 count;
u8 reserved[3];
repeat count times {
    u16 value;
    u16 reserved;
}
```

Count is bounded to 16. The project-0x0c83 row map has 46 entries:

```text
0..15, 0..15, 2..15
```

The embedded cutoff is 655 and the comparison is strict: a value of 655 is
accepted; 656 is rejected. All 23 profile objects embedded in the analysed DLL
use 655.

## Corpus result

All 1,381 raw Windows frames in
`/home/geoca/sp11-touch-captures/etw_3636_frames_20260506` contain one valid
type-`0x04` record with 16 bins:

```text
value 0: 14869 samples
value 1:  6752 samples
value 2:   475 samples
maximum:      2
cutoff:     655
rejections:   0
```

The new parser and filter therefore preserve every existing corpus result.
Their practical value is source fidelity, safe parsing of a previously ignored
firmware field, and diagnostics if a future panel frame raises the NSR value.

## Kernel behavior

The Phase 55 client now:

- validates the nested stream and rejects overruns, invalid counts, truncated
  type-`0x04` payloads, and duplicate type-`0x04` records;
- disables the optional filter when metadata or type `0x04` is absent;
- applies the recovered 46-row mapping and strict cutoff;
- exposes validity, count, maximum observed value, cutoff, and rejection count
  through the existing read-only `state` attribute.

No bus output, firmware write, calibration write, or live module reload is
part of this phase.
