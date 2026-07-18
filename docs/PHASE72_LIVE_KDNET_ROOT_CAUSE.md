# Phase 72 live KDNET record and corrected interpretation

Phase 72 eliminated the frequent class-3 panel-reset storm on live hardware,
but its original explanation was wrong. The first analysis treated a fixed
72-byte debugger dump as though every displayed byte belonged to the transfer.
The capture's explicit transfer length and HID-SPI content length prove that
Windows sends a one-byte logical payload for `SET_FEATURE 0x05` and `0x70`, not
the six-byte payload originally documented.

See [PHASE72_KDNET_ERRATUM.md](PHASE72_KDNET_ERRATUM.md) for the byte arithmetic,
capture hash, and exact evidentiary boundary. This document records what remains
proven and what Phase 72 actually changed.

## What the capture proves

The session observed the shipping Windows stack on the Surface Pro 11 (Windows
build 26100) with resolved `hidspi.sys` PDB symbols. The state machine exposes
three distinct paths:

- `ResettingOnStartup`: cold boot;
- `ResettingOnD3D0`: power/standby transition;
- `ClearingStateOnDeviceInitiatedReset`: panel-initiated reset.

Their traffic differs. The captured facts relevant to Linux are:

- Windows sends 63-byte `OUTPUT_REPORT 0x09` frames during initialization and
  panel-reset recovery.
- Windows sends the four 16-byte `OUTPUT_REPORT 0x65` axis reports during cold
  initialization, but not during device-initiated-reset recovery.
- Device-reset recovery re-arms reports `0x05`, `0x70`, and `0x56` together
  with `0x09`, while standby uses a lighter path.
- The fixed `SET_FEATURE 0x56` payload is
  `bc e6 4a 2e 86 78 00`.
- The logical payloads of captured `SET_FEATURE 0x05` and `0x70` writes are
  each the single byte `01`.

The capture therefore corrected the older claim that report `0x09` was
unsupported and established that `0x65` has a lifecycle boundary. It does not
establish that a truncated feature payload caused the Linux reset storm.

## What Phase 72 changed

The Phase 72 switch performs a coupled experiment after Linux reads
`GET_FEATURE 0x70`:

1. retain the returned content (`02` on the tested Linux boot);
2. send `SET_FEATURE 0x70 = 01 02` instead of `01`;
3. send a short `OUTPUT_REPORT 0x09 = 8e 02`;
4. retain the proven `SET_FEATURE 0x56` token.

Stage 4 continues to send `SET_FEATURE 0x05 = 01`. The derived two-byte
`SET_FEATURE 0x70` and short two-byte `0x09` are not byte-for-byte Windows
traffic: Windows' captured feature content is one byte and its `0x09` content
is 63 bytes.

## Hardware validation

The combined Phase 72 sequence was deployed in an isolated GRUB entry on
2026-07-17. Its boot log reported:

```text
phase72: GET_FEATURE 0x70 config len=1 bytes=02
phase72: SET_FEATURE 0x70 derived len=2 bytes=01 02
phase72: OUTPUT_REPORT 0x09 len=2 bytes=8e 02
touch controller initialized recoveries=1 resets=0
```

The panel then completed roughly 5 hours 50 minutes of use, including deliberate
stress, with zero panel resets. The preceding baseline reset every 2-7 seconds
under sustained touch. This proves that the combined Phase 72 sequence removed
the observed reset storm on that hardware session.

It does **not** isolate which change produced the benefit. Report `0x09` is a
strong candidate because the Windows capture confirms that report ID belongs to
initialization and recovery, but the Linux short report is not the captured
Windows payload. The appended `02`, an interaction between both writes, timing,
or another coupled effect may also be responsible.

## Production consequence

Phase 75 retains the hardware-validated Phase 72 sequence. Removing or changing
it in production merely to resemble Windows more closely would discard strong
device evidence without an isolated replacement test. Any causal experiment
must use a separate branch and boot entry and vary one element at a time.

The accurate project statement is therefore:

> Phase 72 eliminated the reset storm empirically; its mechanism is not yet
> isolated, and the sequence is not a byte-for-byte Windows port.
