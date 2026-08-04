# Current lead / next steps (updated 2026-08-04)

Start with [PHASE72_KDNET_ERRATUM.md](PHASE72_KDNET_ERRATUM.md). The earlier
claim that Windows sends six logical bytes in feature reports `0x05` and `0x70`
was caused by reading beyond `content_len` in a fixed-size debugger dump.

## Current known state

- Phase 91 is the hardware-validated production DMA baseline. Two cold boots
  completed 14,950 Heat frames with zero reset, protocol, transport, or Heat
  errors. Phase 75 is retained as the previous DMA rescue entry.
- Its coupled Phase 72 sequence eliminated the observed reset storm over a
  roughly six-hour stress session.
- The sequence differs from captured Windows traffic: Linux sends derived
  `SET_FEATURE 0x70 = 01 02` and short `OUTPUT_REPORT 0x09 = 8e 02`; Windows
  declares one logical content byte for `0x70` and 63 bytes for `0x09`.
- The reason Phase 72 works is not isolated.
- Report `0x65` is cold-boot-only in the Windows capture. Its version bytes
  match the touchscreen CFU offer and GET `0x60`, identifying it as
  update-management traffic with high confidence. Replaying it in the common
  Phase 74 recovery path caused a reset loop.
- The returned low-level capture proves a Windows host-timeout reset and
  descriptor re-enumeration path, but it did not capture a naturally
  panel-initiated reset.
- Five complete report-`0x09` variants contain dynamic feedback fields. Static
  analysis identifies display state, hinge angle, persistent FastHostId,
  feedback-manager sequence/validity state, provider data, and retained-buffer
  bytes. A single static 63-byte replay is therefore not valid Windows parity.
- An independent 33.336-second Windows SPB trace contains 1,381 raw Heat
  bodies but only one adjacent attach-time A1/A5 pair. Report `0x09` is not a
  per-frame live-contact channel; see
  [WINDOWS_SPB_DEEP_TRACE_AUDIT.md](WINDOWS_SPB_DEEP_TRACE_AUDIT.md).
- A fresh build-26200 Windows SPB capture after a controlled MSHW0485 PnP
  restart reproduces the one-byte `SET_FEATURE 0x70 = 01`, the 63-byte A1/A5
  feedback model, and 1,241 Heat bodies while showing a third valid
  cross-owner attach interleaving. Native `logman` + `tracerpt` preserves the
  payload stream, so this bus-level work no longer requires WPA or KDNET. See
  [WINDOWS_SPB_20260804_LIVE_RESTART.md](WINDOWS_SPB_20260804_LIVE_RESTART.md).
- The firmware resource CLI proves `PRE_OS` and `Normal (Full Frame)` modes and
  the panel configuration independently confirms the 68-by-46 Heat geometry.
  Feature `0x70` is ruled out as that selector: the installed Surface pen
  adaptation driver identifies it as the one-byte host/OOB auto-bonding
  capability report for Slim Pen 2 / MPP 2.6 hardware. Windows instead names
  Feature `0x05 = 01` **Switch Mode Feedback**: TouchPenProcessor resolves
  vendor usage `0xff00:0x00c8`, constructs `{0x05, 0x01}`, and sends it during
  normal Heat initialization. The firmware independently names report-mode
  value `1` as `Normal (Full Frame)`, and a fresh SPB restart trace enters
  continuous 3,636-byte Heat streaming 163.965 ms after the switch. This is
  strong evidence for the production-HID full-frame bridge, although the
  panel-side table-driven HID consumer is not yet linked directly to firmware
  command 107. See
  [WINDOWS_FEATURE70_AUTOBONDING_RE.md](WINDOWS_FEATURE70_AUTOBONDING_RE.md) and
  [WINDOWS_FEATURE05_SWITCH_MODE_RE.md](WINDOWS_FEATURE05_SWITCH_MODE_RE.md).

## Safe investigation order

Keep Phase 91 unchanged and use a separate branch and one-shot GRUB entry for each
experiment. Change one variable at a time:

1. preserve Phase 91 as the production control and Phase 75 as the previous
   lower-chronology comparison;
2. retain Phase 82 only as an observation: its one-byte `SET_FEATURE 0x70`
   startup was noisy before stabilizing and did not replace the control;
3. retain Phase 80/81 host-fault safeguards independently from feature/report
   experiments;
4. retain Phase 84 as the preserved initialization-only control; the
   completed hardware run stopped at the first RX transfer with exact Windows
   GO flags; Phase 87 proved Linux `LINK` completes RX but still returned no
   valid reset header; Phase 88 restored Linux GENI initialization but returned
   `ff ff ff ff`, so Phase 89 restores Linux's normal GPI ring geometry while
   retaining the Windows upper chronology; Phase 89 returned the same header,
   so Phase 90 isolated Phase 75 versus Windows power/reset ordering and
   reached Heat; Phase 91 applies the measured Windows response cadence after
   an immediate Linux second-header read preceded the live reset storm, and is
   now validated across normal and immediate-login cold-boot stress;
5. treat Feature `0x70` as resolved pen auto-bonding traffic and Feature
   `0x05 = 01` as the host-side Switch Mode Feedback / **enable HEAT reporting
   mode** path. `HeatCore.dll` independently sets descriptor usage
   `0xff00:0x00c8` through `HidP_SetUsageValue`; mode `1` is used when the
   processor becomes loaded, on reset, and when restoring an already-active
   HEAT path after monitor power returns, while deinitialization uses mode `0`.
   `InitializeHardware` itself only queries properties and registers the
   monitor-power callback. Do not change the
   hardware-validated Phase 91 chronology merely to make it more literal. The
   remaining mode-selector work is panel-side: reach the generic/table-driven
   HID Feature consumer or the underlying report-mode state from resource/HID
   registration flow, and determine whether the production `0xff00:0x00c8`
   handler reaches the same state exposed by engineering `SetReportMode`;
   separately establish the minimum Heat-only report-`0x09` feedback before
   testing any complete 63-byte path;
6. use a low-overhead reset-only KDNET soak to capture one genuine
   panel-initiated reset.

Do not put `0x65` in the shared recovery path. Do not infer logical content from
bytes outside a packet's declared `content_len`, even when those bytes appear in
the rounded transfer or debugger dump.

Contact behavior must be tested independently from those transport experiments.
Phase 76 preserves the complete Phase 75 setup/recovery sequence and changes
only assignment, final centroid/output coordinates, and strong-contact
admission. Compare keyboard cadence, display edges, slow drags, two-finger
crossing, gesture continuity, `behavior_stats`, and reset counters against the
Phase 75 control before considering promotion.

## Evidence boundary

The 33,851-byte mode-setup log is committed under
`evidence/kdnet/2026-07-17/`. The larger returned lifecycle logs remain in the
private evidence store; their hashes and verified findings are recorded in
[KDNET_20260718_LIFECYCLE_CAPTURE.md](KDNET_20260718_LIFECYCLE_CAPTURE.md) and
[KDNET_20260718_FULL_SESSION_AUDIT.md](KDNET_20260718_FULL_SESSION_AUDIT.md).
The firmware payload identity, validated CFU unwrapping, exact descriptor
match, and Ghidra analysis boundary are recorded in
[TOUCH_FIRMWARE_UPDATE_RE.md](TOUCH_FIRMWARE_UPDATE_RE.md).
The appended descriptor/CLI/logger/configuration records are documented in
[FIRMWARE_RESOURCE_CONTAINER.md](FIRMWARE_RESOURCE_CONTAINER.md).
