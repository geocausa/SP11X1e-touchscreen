# Windows CFU collection boundary

## Why cold chronology is not permission to replay report 0x65

The complete Windows cold trace contains a separate collection attach after
the raw-Heat and device-config owners are already active:

```text
GET_FEATURE 0x60
OUTPUT_REPORT 0x65 = 00 00 ff a0 00 00 00 00 00 00 00 00 00 00 00 00
OUTPUT_REPORT 0x65 = 01 00 ff a0 00 00 00 00 00 00 00 00 00 00 00 00
OUTPUT_REPORT 0x65 = 00 00 12 a0 89 14 00 3f ff ff ff ff 04 04 75 00
OUTPUT_REPORT 0x65 = 02 00 ff a0 00 00 00 00 00 00 00 00 00 00 00 00
GET_FEATURE 0x73 -> 90 01
```

The 1,484-byte descriptor places `0x60` and `0x65` in the `0xff0b/0x0101`
top-level collection. Windows binds that child separately through UMDF. The
third output carries firmware version `0x3f001489`, exactly matching both the
GET `0x60` inventory and the extracted firmware offer. This is collection
inventory/update traffic, not a Heat-mode command.

## Negative hardware evidence

Phase 74 replayed the four captured report-`0x65` bodies in the wrong lifecycle
and produced 15–17 resets. A later isolated replay stopped raw Heat but did not
produce processed report `0x40`; the panel then reset at roughly its calibration
timer cadence. Those tests prove that byte equality without owner state is not
Windows parity.

## Static boundary

The fully analyzed `TouchPenProcessor0C83.dll` contains the raw processing and
feedback-provider attach path. Its `SurfaceHeatProcessor::OnDeviceAttached`
initializes A1/A5 feedback, but the traced attach path and a targeted
decompiler/symbol search found no constructor for the `a0ff`/`a012`
report-`0x65` records. This agrees
with the live topology: the collection is hosted by a separate UMDF layer.

Therefore `windows_init_parity` stops after the exact device-config exchange at
`windows-cfu-owner-required`. Crossing this boundary requires either the UMDF
host binary/configuration that constructs and consumes this inventory protocol,
or a new KDNET capture that includes its callbacks and report-`0x65` responses.
Until then the driver sends no `0x65`, changes no firmware, enables no Heat, and
does not claim that the whole Windows cold attach is complete.
