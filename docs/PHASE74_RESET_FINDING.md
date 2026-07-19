# Phase 74 reset-reproducer finding

Phase 74 was an intentionally isolated fault-injection experiment on the
7.1.3 DMA stack. Its resetting source is not part of the production driver and
must not be merged or made the saved GRUB default.

## Experiment

The laboratory client independently gated three additions based on the
then-current Windows-trace interpretation:

- a derived second `SET_FEATURE 0x05` after `GET_FEATURE 0x70` (the later
  transfer-length audit disproved the claimed Windows feature payload);
- four captured `OUTPUT_REPORT 0x65` payloads;
- a post-recovery `GET_FEATURE 0x70` readiness verification.

The fault-reproducer deliberately placed the apparently cold-boot-only `0x65`
sequence inside the common full-reinitialization path, causing every panel
reset to replay it.

## On-device result (2026-07-18)

- `axis_0x65=0`: zero panel resets during a 4 minute 28 second short run.
- `axis_0x65=1`: 17 panel resets during a 1 minute 39 second run.
- `axis_0x65=1` with audio blacklisted: 15 panel resets; disabling audio did
  not remove the failure.

This isolates replay of `0x65` in the recovery lifecycle as the trigger in
that implementation. Subsequent firmware analysis explains why: the cold-only
payload carries the exact touchscreen CFU offer version also returned by GET
`0x60`, and report `0x65` belongs to the firmware-update collection. It is
update-management traffic with high confidence, not an ordinary recovery
handshake. This does **not** prove that the captured bytes are intrinsically
wrong in their real CFU lifecycle; their placement in common touch recovery
was wrong. Production Phase 75 therefore keeps `0x65` out of that path. See
[TOUCH_FIRMWARE_UPDATE_RE.md](TOUCH_FIRMWARE_UPDATE_RE.md) and
[PHASE72_KDNET_ERRATUM.md](PHASE72_KDNET_ERRATUM.md) before interpreting any
Phase 74 feature-report experiment.

The local-only Phase 74 branch and boot artifact may be retained to reproduce
the failure, but neither belongs in production releases.
