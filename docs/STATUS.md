# Current status and boundaries

## Production baseline

Phase 91 is the current hardware-validated baseline for the OLED Surface Pro
11 (`MSHW0485`) on `7.1.3-sp11-baseline1+`:

- QSPI protocol 9 over GPI-DMA;
- Phase 75's Linux-integrated lower transport and power/reset sequence;
- recovered Windows upper initialization and bounded CFU no-update chronology;
- Windows-measured 490--550 microsecond header/body cadence and one complete
  response per IRQ;
- raw Heat report decoding and up to ten type-B multi-touch slots;
- single-finger input, dragging, two-finger pinch/zoom, and three-finger
  desktop gestures;
- bounded class-3 and host-fault recovery;
- distinct production and FIFO module/DT identities;
- 14,950 Heat frames across two cold boots with zero panel resets, invalid
  headers, transport faults, host-fault recoveries, or Heat errors.

This focused validation is not yet an extensive multi-day soak. Phase 91 is
the best current baseline for the tested OLED SP11 and exact kernel; the
previous DMA and FIFO fallbacks remain required.

The production driver is `phase55/modules/mshw0485_touch.c`. Running `make`
builds its matched client, GENI controller, and GPI-DMA modules. Phase 75 is
the previous DMA rescue image and the 7.1.3 FIFO build is the final fallback.
See [BASELINE_DMA_PHASE91.md](BASELINE_DMA_PHASE91.md).

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
  image; no firmware payload path is present. Phase 86 keeps both checkpoints
  intact and admits Heat only after the exact CFU no-update path and final
  report `0x73` have validated; see
  [PHASE86_WINDOWS_HEAT.md](PHASE86_WINDOWS_HEAT.md).
  `spi_geni_qcom.sp11_windows_se_init=1` additionally removes the generic
  Linux GENI init/mode writes and applies the cold-captured, guarded Windows
  13-write controller sequence. Phase 84 reached the first bidirectional read
  but timed out because the exact Windows GO omitted Linux's required `LINK`
  coupling. Phase 87 isolates that one adaptation while retaining the Windows
  ring geometry. It completed RX but received no valid reset header. Phase 88
  retained the rings and `LINK` while restoring Linux's generic GENI
  initialization and mode selection; its untouched boot returned
  `ff ff ff ff`. Phase 89 therefore restores the complete Phase 75 lower
  transport, including normal Linux GPI ring geometry; it returned the same
  all-ones header. Phase 90 retains that transport and isolates only the
  power/reset chronology. It completed the full upper chronology and delivered
  1,984 valid Heat frames, but one immediate second-header read desynchronized
  the stream and was followed by six panel resets. Phase 91 applies the
  measured Windows header/body delay and one-response-per-interrupt policy.
  Two Phase 91 cold boots, including immediate login-screen stress, completed
  14,950 Heat frames with zero resets, invalid headers, or transport faults,
  making it the promoted production baseline. See
  [PHASE84_HARDWARE_RESULT.md](PHASE84_HARDWARE_RESULT.md),
  [PHASE87_HARDWARE_RESULT.md](PHASE87_HARDWARE_RESULT.md),
  [PHASE87_LINUX_LINK_HEAT.md](PHASE87_LINUX_LINK_HEAT.md), and
  [PHASE88_LINUX_SE_WINDOWS_HEAT.md](PHASE88_LINUX_SE_WINDOWS_HEAT.md),
  [PHASE88_HARDWARE_RESULT.md](PHASE88_HARDWARE_RESULT.md), and
  [PHASE89_LINUX_TRANSPORT_WINDOWS_HEAT.md](PHASE89_LINUX_TRANSPORT_WINDOWS_HEAT.md),
  [PHASE89_HARDWARE_RESULT.md](PHASE89_HARDWARE_RESULT.md), and
  [PHASE90_PHASE75_POWER_WINDOWS_HEAT.md](PHASE90_PHASE75_POWER_WINDOWS_HEAT.md),
  [PHASE90_HARDWARE_RESULT.md](PHASE90_HARDWARE_RESULT.md),
  [PHASE91_WINDOWS_READ_CADENCE.md](PHASE91_WINDOWS_READ_CADENCE.md), and
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
  does not replace Phase 75. Static analysis now identifies report `0x70` as
  Surface pen host/OOB auto-bonding capability traffic, not the Heat/full-frame
  mode selector; see
  [WINDOWS_FEATURE70_AUTOBONDING_RE.md](WINDOWS_FEATURE70_AUTOBONDING_RE.md).
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
- Windows HEAT user-mode ownership is now narrowed to `dwm.exe -> ISM.exe ->`
  `HeatCore.dll` plus the exact `TouchPenProcessor0C83.dll`: `heat.inf` grants
  the DWM security group access, and a controlled restart shows DWM spawning a
  replacement ISM that loads those modules and owns the COL02 HEAT registry
  state. The usable HeatCore TraceLogging provider is
  `Microsoft.Windows.Heat.HeatCore` / `{55A5DC53-E24E-5B53-5B52-EA83A0CC4E0C}`.

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
CLI proves that firmware distinguishes PRE_OS from normal full-frame mode.
Feature `0x70` is now ruled out as that selector, while the Heat software
processor identifies Feature `0x05 = 01` as **Switch Mode Feedback** and sends
it during normal Heat initialization. Microsoft's generic `HeatCore.dll`
independently identifies descriptor usage `0xff00:0x00c8` as the HEAT reporting-
mode switch, using value `1` for initialize/reset and `0` for deinitialize. Its
value and observed transition into
continuous Heat streaming strongly match firmware report-mode value `1 = Normal
(Full Frame)`, but the table-driven panel-side HID consumer has not yet been
connected directly to that firmware state. See
[WINDOWS_FEATURE05_SWITCH_MODE_RE.md](WINDOWS_FEATURE05_SWITCH_MODE_RE.md).
The ARC subtype consumer and natural panel-reset trigger remain unresolved.
The repo-wide status of resolved, narrowed, validation-blocked, and pure
engineering items is tracked in
[OPEN_QUESTIONS_AUDIT_20260804.md](OPEN_QUESTIONS_AUDIT_20260804.md). The exact
matched GENI/GPI portability boundary is documented in
[TRANSPORT_PORTABILITY_AUDIT_20260804.md](TRANSPORT_PORTABILITY_AUDIT_20260804.md).

The older complete Windows SPB payload trace provides an independent cadence
check: 1,381 raw Heat bodies coexist with exactly one attach-time A1/A5 pair,
not per-frame report-`0x09` traffic. It also records a different valid
multi-owner restart interleaving. See
[WINDOWS_SPB_DEEP_TRACE_AUDIT.md](WINDOWS_SPB_DEEP_TRACE_AUDIT.md).

`main` represents the best validated project baseline, not a claim of generic
hardware support, Windows parity, or upstream acceptance.

## 2026-08-04 repo-wide closure update

- Basic Heat streaming does **not** require Output Report `0x09`: the cold-boot-validated Phase 62 tree (`e35fbc4`) sends no report-09 payload and streamed more than 1,500 decoded Heat frames. Windows A1/A5 feedback is therefore control-plane state, not a mandatory Heat unlock.
- Windows finger Touch does **not** support a Pressure capability in HeatCore; Width/Height Geometry is the relevant public contact-shape ABI. See [WINDOWS_TOUCH_CONTACT_ABI_RE.md](WINDOWS_TOUCH_CONTACT_ABI_RE.md).
- The processor computes raw Width/Height as inclusive component bounds (`max-min+1`) and optionally applies per-track smoothing. The smoothing block is project configuration at offset `+0x294` (float alpha at `+0`, enable byte at `+4`); the active file/runtime value is not yet proven.
- The remaining protocol-side private boundary is the ARC production HID SET-feature dispatcher that consumes Feature `0x05`; Windows-side semantics are already resolved.
- Human labels for the four processor classifier classes remain unproven. Normal touch output accepts classes 0 and 2; telemetry vocabulary names Finger/FingerAwareness/Smear/SmearAwareness/Bunch, but those names are not safely index-mapped.
- Genuine panel-originated reset capture, labelled palm/edge/close-contact validation, and system-suspend hardware validation remain evidence-blocked rather than static-analysis unknowns.
