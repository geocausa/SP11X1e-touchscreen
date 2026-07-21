# Current status and boundaries

## Production baseline

Phase 75 is the current hardware-validated baseline for the OLED Surface Pro
11 (`MSHW0485`) on `7.1.3-sp11-baseline1+`:

- QSPI protocol 9 over GPI-DMA;
- raw Heat report decoding and up to ten type-B multi-touch slots;
- single-finger input, dragging, two-finger pinch/zoom, and three-finger
  desktop gestures;
- empirically validated Phase 72 exchange (`GET 0x70 = 02`, derived
  `SET 0x70 = 01 02`, `OUTPUT 0x09 = 8e 02`), whose benefit is not yet
  causally isolated and whose bytes do not reproduce the captured Windows
  exchange;
- bounded class-3 reset recovery;
- distinct production and FIFO module/DT identities;
- zero panel resets and zero transport errors in the Phase 75 validation boot.

The production driver is `phase55/modules/mshw0485_touch.c`. Running `make`
builds its matched client, GENI controller, and GPI-DMA modules. Phase 73 and
the 7.1.3 FIFO build remain bootable fallbacks.

The corrected KDNET interpretation is recorded in
[PHASE72_KDNET_ERRATUM.md](PHASE72_KDNET_ERRATUM.md). It retracts the former
“truncated feature payload” explanation without retracting the Phase 72/75
hardware results.

Phase 76 is an opt-in behavior-only experiment over this exact baseline. It
adds recovered sensor-space assignment, direct output coordinates, the bounded
normal centroid branch, and two-frame strong-contact admission. That behavior
subsequently booted and provided ordinary and multi-touch input. Phase 77 adds
gated software re-enumeration after a panel reset and also completed clean
cold boots with thousands of Heat frames and zero parser/reset errors, but its
natural panel-reset branch has not yet been exercised by a captured reset; see
[PHASE76_BEHAVIOR.md](PHASE76_BEHAVIOR.md) and
[PHASE77_GATED_RECOVERY.md](PHASE77_GATED_RECOVERY.md).

## Explicitly experimental

- `mshw0485_touch.windows_init_parity=1` is an input-disabled cold-bring-up
  laboratory path. It follows captured Windows collection ownership through
  provider-built A1/A5 feedback and the exact device-config exchange, then
  stops before CFU report `0x65`. Dynamic provider inputs are invalid by
  default and must be supplied explicitly; see
  [WINDOWS_INIT_PARITY.md](WINDOWS_INIT_PARITY.md).
  The installed `SurfaceCFUOverHid` owner, its offer constructor, and the
  panel's complete reject-old/same response path are now statically and
  dynamically decoded. They remain outside Phase 84 pending a distinct gated
  image; no firmware payload path is present.
  `spi_geni_qcom.sp11_windows_se_init=1` additionally removes the generic
  Linux GENI init/mode writes and applies the cold-captured, guarded Windows
  13-write controller sequence. It is confined to Phase 84/85; see
  [WINDOWS_CONTROLLER_INIT_PARITY.md](WINDOWS_CONTROLLER_INIT_PARITY.md).
- `mshw0485_touch.windows_orchestrator=1` enables recovered Windows lifecycle
  behavior whose provider-owned context fields are not fully proven. It is
  read-only and defaults off.
- `mshw0485_touch.behavior_v2=1` selects the isolated Phase 76 contact profile.
  It is read-only, defaults off, is mutually exclusive with
  `windows_orchestrator`, and does not change transport or reset recovery.
- `mshw0485_touch.reset_recovery_v2=1` selects Phase 77's gated software
  descriptor re-enumeration after a panel reset. Clean cold boot is validated;
  the reset branch remains experimental.
- `mshw0485_touch.reset_storm_breaker=1` selects Phase 78's bounded escalation.
  It was hardware exercised but did not remove the underlying reset storm.
- `mshw0485_touch.feature70_one_byte=1` is the Phase 79/82 single-axis protocol
  experiment. It corrects the logical Windows SetFeature length while
  deliberately retaining Phase 72's short report `0x09`; Phase 82 combines it
  with the validated Phase 81 host safeguards. Its first cold boot had 10
  panel resets and three recovered protocol faults during startup, then ran
  7,410 Heat frames without another fault. This is improved but not clean and
  does not replace Phase 75.
- `mshw0485_touch.host_fault_recovery=1` selects Phase 80's bounded cold
  recovery after an IRQ transport/protocol/drain failure. It is backed by the
  captured Windows timeout lifecycle. Its first boot recovered five protocol
  faults successfully but was too eager to reset on an invalid trailing read.
- `mshw0485_touch.ready_quiesce=1` selects Phase 81's guarded post-read check.
  It ignores an invalid trailing header only after GPIO51 deasserts; persistent
  invalid headers still enter Phase 80 recovery. Its cold boot quiesced 17
  trailing reads with zero host faults, proving the classification fix, while
  24 genuine panel resets continued independently.
- Phase 74 is a local reset reproducer. Replaying its captured report `0x65`
  sequence during recovery caused 15-17 resets. Firmware analysis now
  identifies `0x65` as CFU/update-management traffic with high confidence,
  independently confirming that it does not belong in ordinary recovery; see
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
- No firmware is flashed or modified. Windows binaries are not redistributed.
  One small textual KDNET log is retained for reproducibility; the larger
  private captures are represented by hashes and derived findings.

The complete July 18 evidence boundary is recorded in
[KDNET_20260718_FULL_SESSION_AUDIT.md](KDNET_20260718_FULL_SESSION_AUDIT.md),
and the independently reproducible CFU/ARC extraction is documented in
[TOUCH_FIRMWARE_UPDATE_RE.md](TOUCH_FIRMWARE_UPDATE_RE.md). The firmware image
contains the exact live HID descriptor. The Windows report-`0x09` producer and
its dynamic display/feedback fields are documented in
[WINDOWS_REPORT09_FEEDBACK_RE.md](WINDOWS_REPORT09_FEEDBACK_RE.md); the ARC
resource container and firmware-side semantic corroboration are documented in
[FIRMWARE_RESOURCE_CONTAINER.md](FIRMWARE_RESOURCE_CONTAINER.md). The resource
CLI proves that firmware distinguishes PRE_OS from normal full-frame mode, but
does not prove that HID Feature `0x70` selects it. The ARC subtype consumer and
natural panel-reset trigger remain unresolved.

The older complete Windows SPB payload trace provides an independent cadence
check: 1,381 raw Heat bodies coexist with exactly one attach-time A1/A5 pair,
not per-frame report-`0x09` traffic. It also records a different valid
multi-owner restart interleaving. See
[WINDOWS_SPB_DEEP_TRACE_AUDIT.md](WINDOWS_SPB_DEEP_TRACE_AUDIT.md).

`main` represents the best validated project baseline, not a claim of generic
hardware support, Windows parity, or upstream acceptance.
