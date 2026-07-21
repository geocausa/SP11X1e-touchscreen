# Current lead / next steps (updated 2026-07-19)

Start with [PHASE72_KDNET_ERRATUM.md](PHASE72_KDNET_ERRATUM.md). The earlier
claim that Windows sends six logical bytes in feature reports `0x05` and `0x70`
was caused by reading beyond `content_len` in a fixed-size debugger dump.

## Current known state

- Phase 75 is the hardware-validated production baseline.
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
- The firmware resource CLI proves `PRE_OS` and `Normal (Full Frame)` modes and
  the panel configuration independently confirms the 68-by-46 Heat geometry.
  It does not yet connect HID Feature `0x70` to that report-mode selector.

## Safe investigation order

Keep Phase 75 unchanged and use a separate branch and GRUB entry for each
experiment. Change one variable at a time:

1. preserve the Phase 75 sequence as the control;
2. retain Phase 82 only as an observation: its one-byte `SET_FEATURE 0x70`
   startup was noisy before stabilizing and did not replace the control;
3. retain Phase 80/81 host-fault safeguards independently from feature/report
   experiments;
4. retain Phase 84 as the preserved initialization-only control; the
   completed hardware run stopped at the first RX transfer with exact Windows
   GO flags; Phase 87 proved Linux `LINK` completes RX but still returned no
   valid reset header, so Phase 88 now restores Linux GENI initialization
   while retaining captured rings, `LINK`, and the Windows upper chronology;
5. use the completed Windows producer trace and the decoded resource/logger
   evidence in
   [WINDOWS_REPORT09_FEEDBACK_RE.md](WINDOWS_REPORT09_FEEDBACK_RE.md) to locate
   the generic HID feedback dispatcher, determine whether Feature `0x70`
   selects normal full-frame mode, and establish the minimum Heat-only
   feedback before testing any complete 63-byte path;
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
