# July 2026 KDNET lifecycle capture

This note records the evidence boundary from the low-level Windows HID-SPI
session returned on 2026-07-18. It supersedes lifecycle claims inferred from
fixed-size buffer dumps without explicit transfer boundaries.

The later end-to-end pass, including debugger-induced timing effects and the
firmware-update correlation, is in
[KDNET_20260718_FULL_SESSION_AUDIT.md](KDNET_20260718_FULL_SESSION_AUDIT.md).

## Canonical private sources

The raw returned files are retained outside the public source tree because
they contain complete Windows descriptor traffic and debugger state. Their
identities are:

```text
f2405158054c4475a5c225446eccc7873af1e1fa1a6066406a34876ea9ca2d23  sp11_touch_deep_boot2_0924_2026-07-18_23-02-40-797.log
431d48d05a78de130f3d05bc0e2132b62ee1ed9cbb71d41bd1abfd20f6858ed4  sp11_touch_deep_20c4_2026-07-18_22-43-41-830.log
c83b79edee88713a0d933cec1adada685529a321552522f9e49f2c5b51408942  OPERATOR_TIMELINE_20260718.md
6ae8818c22241695fbd68fdf323b49110337f3fee3047668b291f02854925172  sp11_touch_deep_bp_script.txt
```

The earlier complete mode-setup log is committed under
`evidence/kdnet/2026-07-17/`; its SHA-256 is
`fd1f8d439d11a729751fa68ec8788b0a8536b70fe4fc391e853829fe87078ddd`.

`tools/extract_kdnet_hidspi.py` parses both capture formats. It truncates every
debugger dump at `txLen`, then separates the logical HID content at
`content_len`. Tests specifically prevent the old padding/tail mistake.

## Directly observed boundaries

- Windows SetFeature `0x05` and `0x70` each declare one content byte: `01`.
  Their 12-byte rounded transfers may clock three alignment bytes, but those
  bytes are outside the logical HID content.
- SetFeature `0x56` declares seven content bytes:
  `bc e6 4a 2e 86 78 00`.
- OutputReport `0x09` declares 63 content bytes in a 72-byte rounded transfer.
- OutputReport `0x65` declares 16 content bytes and was observed only on the
  cold-start collection path. Its firmware-version bytes identify it as
  CFU/update-management traffic with high confidence; see
  [TOUCH_FIRMWARE_UPDATE_RE.md](TOUCH_FIRMWARE_UPDATE_RE.md).
- The write `e2 00 20 00 01 00 00 00` is the ordinary device-descriptor
  request. It is not a separate reset acknowledgement.

Across the complete July 17 and July 18 logs there are five distinct complete
report-`0x09` payloads. Their non-zero content offsets are:

```text
A0: [0]=8e [1]=a1 [4]=90 [5]=01 [40]=90 [41]=01
A1: [0]=8e [1]=a1 [2]=01 [4]=90 [5]=01 [40]=90 [41]=01
B0: [0]=8e [1]=a5 [3]=02 [39]=90 [40]=01 [46]=40
B1: [0]=8e [1]=a5 [3]=02 [12]=70 [13]=17 [36]=ff [37]=f8
    [39]=90 [40]=01 [43]=04 [44]=ff [46]=40 [48]=ff [49]=02
C:  [0]=8e [1]=a5 [2]=01 [3]=02 [12]=70 [13]=17 [36]=ff
    [37]=f8 [39]=90 [40]=01 [43]=04 [44]=ff [46]=52 [47]=43
    [48]=ff [49]=02
```

The varying fields prove that a single static 63-byte replay is not yet a
sound production replacement for the empirically stable Phase 72 short
report. The capture establishes wire truth, not the ownership or producer of
every dynamic field.

## Host-timeout reset sequence

The operator deliberately paused for 60 seconds between a header and body
read. Windows entered `ResettingSyncEntry`, `Fdo::EvtCxResetDevice`,
`CxClient::ResettingEntry`, and `Fdo::ResetDevice`. About 391 ms later it read:

```text
header: 03 01 40 5a
body:   03 00 00 00
```

That is a reset response. Windows then issued the ordinary device-descriptor
request, read the device descriptor, and continued re-enumeration and setup
until Heat frames resumed. This is direct evidence for recovering a dead host
transfer rather than leaving the collection inert.

## What was not captured

- `ClearingDeviceStateOnResetEntry` did not fire for a naturally
  panel-initiated reset. Breakpoint command listings containing that name are
  not hits.
- The QSPI SE-init breakpoint at `qcspi+0x1b3c8` was armed but never hit.
- The debugger's Wi-Fi breakpoint perturbed deep standby, so this session does
  not prove a complete D3/D0 touchscreen lifecycle.

Therefore the trace must be described as cold startup, host-timeout recovery,
and shallow wake evidence—not as a captured natural panel-reset recovery.

## Static cross-check

Independent inspection of the matching `hidspi.sys` state-machine code shows
that class `0x03` clears cached descriptor fields. Its device-state clear path
frees and reallocates descriptor storage before state-machine enumeration
continues. This supports Phase 77's software descriptor re-enumeration after a
panel reset. It does not reveal the dynamic producer of report `0x09` and does
not justify copying cold-only CFU report `0x65` into recovery.
