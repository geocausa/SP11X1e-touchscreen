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
- Report `0x65` is cold-boot-only in the Windows capture. Replaying it in the
  common Phase 74 recovery path caused a reset loop.
- The returned low-level capture proves a Windows host-timeout reset and
  descriptor re-enumeration path, but it did not capture a naturally
  panel-initiated reset.
- Five complete report-`0x09` variants contain lifecycle-dependent fields. A
  single static 63-byte replay is therefore not ready for production.

## Safe investigation order

Keep Phase 75 unchanged and use a separate branch and GRUB entry for each
experiment. Change one variable at a time:

1. preserve the Phase 75 sequence as the control;
2. test the one-byte `SET_FEATURE 0x70` while retaining the short Phase 72
   `0x09`, isolating the appended `02`;
3. test Phase 80's host-fault recovery independently from feature/report
   changes;
4. recover the owner and producer of the changing report-`0x09` fields before
   testing a complete 63-byte path;
5. use a low-overhead reset-only KDNET soak to capture one natural
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
[KDNET_20260718_LIFECYCLE_CAPTURE.md](KDNET_20260718_LIFECYCLE_CAPTURE.md).
