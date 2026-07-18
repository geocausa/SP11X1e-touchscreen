# Current status and boundaries

## Production baseline

Phase 75 is the current hardware-validated baseline for the OLED Surface Pro
11 (`MSHW0485`) on `7.1.3-sp11-baseline1+`:

- QSPI protocol 9 over GPI-DMA;
- raw Heat report decoding and up to ten type-B multi-touch slots;
- single-finger input, dragging, two-finger pinch/zoom, and three-finger
  desktop gestures;
- Phase 72 mode-config exchange (`GET 0x70 = 02`, derived `SET 0x70 = 01 02`,
  `OUTPUT 0x09 = 8e 02`);
- bounded class-3 reset recovery;
- distinct production and FIFO module/DT identities;
- zero panel resets and zero transport errors in the Phase 75 validation boot.

The production driver is `phase55/modules/mshw0485_touch.c`. Running `make`
builds its matched client, GENI controller, and GPI-DMA modules. Phase 73 and
the 7.1.3 FIFO build remain bootable fallbacks.

## Explicitly experimental

- `mshw0485_touch.windows_orchestrator=1` enables recovered Windows lifecycle
  behavior whose provider-owned context fields are not fully proven. It is
  read-only and defaults off.
- Phase 74 is a local reset reproducer. Replaying its captured report `0x65`
  sequence during recovery caused 15-17 resets; see
  [PHASE74_RESET_FINDING.md](PHASE74_RESET_FINDING.md).
- Suspend/resume callbacks exist but platform suspend is not validated and is
  not claimed safe after earlier whole-device crashes.

## Not implemented or not claimed

- Pen support is deliberately out of scope.
- Pressure, precise contact shape, and reliable merged-finger separation are
  not implemented.
- Palm classification and edge calibration lack sufficient labelled physical
  captures for a production accuracy claim.
- The complete proprietary Windows TouchPenProcessor pipeline is not cloned;
  only bounded, independently implemented behavior supported by static,
  dynamic, corpus, and hardware evidence is present.
- Kernels other than `7.1.3-sp11-baseline1+` require a source-level GENI/GPI
  rebase and hardware validation. A matching module version string is not
  sufficient.
- The driver is out-of-tree and not yet suitable for a mainline Linux
  submission. It depends on matched internal GENI and GPI changes.
- No firmware is flashed or modified. Windows binaries and captures are
  optional read-only research inputs and are not redistributed.

`main` represents the best validated project baseline, not a claim of generic
hardware support, Windows parity, or upstream acceptance.
