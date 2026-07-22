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

## Installed Windows owner and configuration

The exact installed owner was found on the target Windows partition and
inspected read-only:

```text
94534cfcee41ae4ede55e61610cf865d8cefd119ab4b991183e98ac70c7f8acc  SurfaceCFUOverHid.dll
6be77b2183f09554d1fec327393c17e6cfa30c04a5979b80bb15ec6fa86cd931  SurfaceCFUOverHid.inf
0883cc90da9bcf17bd340f0fef0a1cb52e617b31c73caed6debb64e64007aef9  SurfaceTouchG6FwUpdateExtnPackage0C83.inf
fc5772d45dd0a0b239f1f7beca4f71adbda5756ea10e695b3319510ae0bd58af  SurfaceTouchG6_FW_MSHW0485.offer.bin
```

The base INF binds `SurfaceCFUOverHid.dll` to the firmware-update HID usage
`0xff0b/0x0101`. The MSHW0485 extension INF targets `Col06`, selects CFU
protocol 1, and names the 16-byte offer and payload files. The offer is:

```text
00 00 12 00 89 14 00 3f ff ff ff ff 04 04 75 00
```

Its declared version is `0x3f001489`, the same value returned by report
`0x60`. No Microsoft binary or firmware file is copied into this repository;
only file identities and independently derived protocol facts are retained.

## Recovered constructor and complete responses

The ARM64 UMDF binary was imported into a separate Ghidra project. Two
functions close the constructor gap:

- `FUN_18000b320` zeroes a report and constructs the three information
  records as `information_code | 0xa0ff0000`.
- `FUN_18000ac20` copies the selected 16-byte offer, overwrites byte 3 with
  token `0xa0`, and applies the development-only force flags only when their
  independent configuration booleans are set. They are clear in the captured
  production transaction.

The resulting four writes are therefore constructed, not opaque constants.
Every write has an immediate 16-byte DATA response. The three information
records return:

```text
00 00 00 a0 00 00 00 00 ff 00 00 00 01 00 00 00
```

The actual installed offer returns:

```text
00 00 00 a0 00 00 00 00 00 00 00 00 02 00 00 00
```

Using Microsoft's published CFU layout, the DWORDs are token, reserved,
reject reason, and status. Token `0xa0` is echoed. Status `1` accepts each
information record. Status `2` rejects the installed firmware offer with
reason `0`, meaning that the offered firmware is old or the same version.
Consequently Windows sends no payload and flashes nothing in this boot.
`tools/windows_cfu.py` reconstructs and decodes this bounded inventory path;
the lifecycle extractor retains these report-`0x65` DATA acknowledgements
while continuing to omit streaming Heat DATA.

Report `0x60` declares one component in its first byte. Only its header and
first two-DWORD component entry are CFU inventory according to the published
layout. The later bytes that correlate with report `0x56` lie outside that
declared table. They remain useful target-specific provenance but are not
decoded as standardized CFU fields and are not used to reorder the owners.

## Implementation boundary

The fully analyzed `TouchPenProcessor0C83.dll` contains the raw processing and
feedback-provider attach path. Its `SurfaceHeatProcessor::OnDeviceAttached`
initializes A1/A5 feedback, but the traced attach path and a targeted
decompiler/symbol search found no constructor for the `a0ff`/`a012`
report-`0x65` records. This agrees
with the live topology: the collection is hosted by a separate UMDF layer.

Phase 84 still stops after the exact device-config exchange at
`windows-cfu-owner-required`; preserving that checkpoint makes the earlier
owners independently falsifiable on hardware. The former missing-owner gap is
now closed well enough to build a later, separately gated inventory test:

1. GET report `0x60` and validate its exact length;
2. construct start-transaction and start-list records with token `0xa0`;
3. construct the installed offer from a separately supplied 16-byte platform
   value, with both force bits clear;
4. require the captured reject-old/same result before sending end-list;
5. stop without sending any payload if the panel accepts, skips, is busy, or
   returns an unrecognized response.

This is intentionally not called panel initialization. CFU is an independent
inventory/update client that happens to attach during the cold chronology.
It must never be put in ordinary touch recovery, and no firmware payload path
belongs in the touchscreen driver.
