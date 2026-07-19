# July 2026 KDNET full-session audit

This is the end-to-end interpretation of both July 18 KDNET logs, their
operator timeline, breakpoint program, completed HID-SPI transfers, and the
matching firmware-update payload. It deliberately separates natural device
behavior from behavior caused by debugger pauses and high-volume breakpoints.

## Evidence identity

The private canonical files are retained outside the public tree:

```text
f2405158054c4475a5c225446eccc7873af1e1fa1a6066406a34876ea9ca2d23  sp11_touch_deep_boot2_0924_2026-07-18_23-02-40-797.log
431d48d05a78de130f3d05bc0e2132b62ee1ed9cbb71d41bd1abfd20f6858ed4  sp11_touch_deep_20c4_2026-07-18_22-43-41-830.log
c83b79edee88713a0d933cec1adada685529a321552522f9e49f2c5b51408942  OPERATOR_TIMELINE_20260718.md
6ae8818c22241695fbd68fdf323b49110337f3fee3047668b291f02854925172  sp11_touch_deep_bp_script.txt
```

`tools/extract_kdnet_hidspi.py` reconstructs the serialized CxClient request
stream, bounds TX by `txLen`, bounds RX by `rxLen`, and validates a body only
when its declared logical content fits in the completed buffer.

## What the complete session contains

### Cold start

Boot 2 begins with the Windows HID-SPI reset callback and then:

1. reads reset response class `0x03`;
2. requests and reads the 24-byte device descriptor;
3. requests and reads the 1,484-byte HID report descriptor;
4. performs collection-owned feature/output traffic;
5. begins normal input reports.

The observed setup includes GET `0x73`, GET `0x06`, full 63-byte report-`0x09`
A1/B0 writes, SET `0x05={01}`, GET/SET `0x70`, SET `0x56`, GET `0x60`, and
four report-`0x65` exchanges. The SET `0x05` and SET `0x70` logical contents
are one byte. Their other three clocked bytes are alignment/stale-buffer data.

### Clean ordinary use

After roughly 2.5 minutes idle, the first tap produced report `0x08` followed
by Heat report `0x12`. A later approximately 90-second fast two-finger
on-screen typing workload generated no reset marker. A random 15-second host
debugger freeze also caused no reset and touch resumed immediately.

These are important negative observations: the captured Windows session does
not contain a naturally reproduced touch storm or a naturally panel-announced
reset.

### Deliberately expired host transactions

The operator then paused Windows for 60 seconds after a valid header but before
the corresponding body read. On resume, Windows' host deadline had expired and
the HidSpiCx worker initiated reset. The observed reset stack is:

```text
HidSpiCx ResettingSyncEntry
  -> hidspi Fdo::EvtCxResetDevice
  -> CxClient ResettingEntry
  -> Fdo::ResetDevice
```

`ClearingDeviceStateOnResetEntry`, the breakpoint selected for a
device-initiated reset, never fired. These resets demonstrate recovery from a
dead host transaction, not the panel's natural reset trigger.

The first fully instrumented recovery was itself perturbed. After descriptor
enumeration and a GET `0x70`, 81 class-1 report-`0x40` bodies were processed
while per-transfer breakpoints slowed the target, followed by another host
timeout. This stream is input traffic, not a feature reply and not a clean
recovery recipe.

The next recovery completed a different interleaved sequence:

```text
reset response
device descriptor
SET 05
input report 2e
SET 56
report 09 A1 -> input a0
report 09 B0
SET 05
report 09 A1/B0
report 09 A1/B0
```

There is no SET `0x70` in that captured fragment. This proves that the outgoing
writes are produced by multiple collection/lifecycle owners; it does not
justify flattening one observed list into a Linux reset script.

### Shallow standby/wake

The wake pass was interrupted by an unrelated WifiCx diagnostic breakpoint.
The touchscreen `CompletingPowerDownEntry` breakpoint did not fire, so this is
not evidence of a complete D3-to-D0 lifecycle. No reset state fired in this
pass. The traffic does show SET `0x05`, full report-`0x09` variants, GET/SET
`0x70`, SET `0x56`, and later ordinary input.

### QSPI/GPI layer

Controller breakpoints prove the active Windows path is GPI DMA:

```text
hidspi MultiSpiTransfer
  -> SpbCx
  -> qcspi8380 DMA submit / descriptor build
  -> qcgpi8380 event callback
  -> qcspi DPC / request completion
  -> hidspi CxClient completion
```

The completed byte count agrees with the HID-SPI request length. The QSPI
serial-engine initialization breakpoint did not fire in the observed window.
This establishes transport correlation but supplies no evidence that changing
Linux's working GPI-DMA path will improve the early-boot storm.

Two deliberately expired body buffers contain `03 01 40 5a` where a body
prefix should be. One is followed by repeated `03 00 00 00`. Their apparent
content length `0x4001` exceeds the bounded RX buffer, so the parser marks them
malformed. They are not giant class-3 protocol responses.

## Reset count and causality

Boot 1 contains two reset callback chains during heavily instrumented cold
startup. Boot 2 contains seven chains: cold startup, three controlled/secondary
host-timeout events, and three in the controller-correlation tail. No natural
panel-reset breakpoint hit exists in either log.

The session therefore answers how Windows recovers a host-side timeout, but it
does not yet answer what naturally initiates the Linux early-boot storm.

## Report-09 conclusion

The complete logs contain several lifecycle-dependent 63-byte report-`0x09`
payloads. Windows repeats A/B pairs at different layers and changes fields
between cold start and wake. A static B0 replay would discard that ownership
and dynamic context. The proposed Phase 83 single-B0 experiment was therefore
discarded before build or deployment.

## Firmware-update correlation

The exact live 1,484-byte HID descriptor occurs in the unwrapped touchscreen
firmware image. It declares:

| Report | HID kind | Size | Usage page / usage |
| --- | --- | ---: | --- |
| `0x05` | Feature | 1 byte | `0xff00 / 0xc8` |
| `0x09` | Output | 63 bytes | `0xff00 / 0xc9` |
| `0x56` | Feature | 7 bytes | `0xfff4 / 0x03,0x09` |
| `0x70` | Feature | 1 byte | `0xfff4 / 0x10,0x22` |
| `0x65` | Output + Input | 16 bytes each | `0xff0b` vendor usages |

The update offer version `89 14 00 3f` (`0x3f001489`) occurs in GET `0x60`
and in the cold-only report-`0x65` payload. Together with the firmware-update
INF binding to collection 06—and report `0x65` residing in the descriptor's
sixth top-level application collection—this identifies `0x65` as
CFU/update-management traffic with high confidence. It must not be promoted
into ordinary reset recovery. This independently explains the Phase 74
regression mechanism.

## Engineering decision

Keep Phase 75 as the saved baseline and Phase 82 as an isolated observation.
Do not deploy the discarded static-B0 Phase 83. The next protocol experiment
must come from one of these evidence-producing routes:

1. capture a genuine panel-announced reset with the device-reset breakpoint;
2. trace the Windows owner that constructs each report-`0x09` variant;
3. trace the ARC firmware handler for report `0x09` to recover its field
   semantics and state transitions;
4. reproduce the Linux early-boot storm with bounded timestamps while avoiding
   debugger-induced timing changes.
