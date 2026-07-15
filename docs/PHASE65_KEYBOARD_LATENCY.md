# Phase 65 touchscreen-keyboard latency

Phase 65 addresses intermittent pauses and omitted characters observed while
typing quickly with GNOME's on-screen keyboard. It is an isolated follow-up
to the hardware-validated Phase 64 classifier entry.

## Reproduction evidence

The first 37-second keyboard capture emitted 173 contact-down transitions.
Median key-down duration was 47.2 ms, but the input stream contained a 1.305
second gap. The user reproduced visible pauses and missing characters.

A second 35.3-second capture paired an input-event reader with entry and
return probes around `g6ts_find_contacts`:

```text
raw classifier frames:       3054
raw touch-present frames:    1274
raw touch-present runs:       159
emitted contact downs:        163
minimum raw run:            5 frames
median classifier time:      55 us
95th percentile time:       120 us
maximum classifier time:    179 us
```

The fixed-point classifier is not causing the pause, and the reproduction did
not contain a one- or two-frame physical tap for the existing confirmation
gate to discard. The kernel emitted at least as many contact transitions as
the raw touch-present runs; adjacent fast taps can remain touch-present across
their boundary and therefore explain the small excess.

The deployed controller artifact did reveal a separate production defect. A
bring-up build logged every successful paired DMA transfer at `INFO` level.
The rate limiter reported 600 to 1,100 suppressed callbacks in repeated
five-second windows while typing. The repository source already uses
`dev_dbg()` for this success path, but Phase 64's initramfs inherited the noisy
installed controller module instead of the matched external build.

## Changes

- Embed the matched `spi-geni-qcom.ko` with debug-only successful-transfer
  logging in the dedicated initramfs.
- Reduce the normal evidence window for a classifier-approved new touch from
  three frames to two. This lengthens the key-down interval presented to the
  compositor without admitting single-frame noise.
- Retain five-frame confirmation for weak or classifier-denied candidates and
  five- or eight-frame confirmation for nearby split candidates.
- Retain the classifier, broad palm guard, assignment, smoothing, dropout
  recovery, and transport recovery from Phase 64.

The evidence-window change is mirrored by the deterministic Python tracker
and an explicit two-frame admission regression. The legacy three-frame policy
remains directly tested as a configurable anti-noise case.

## Validation before deployment

- 34 unit tests pass.
- Matched `7.1.1-sp11-gpicmp1+` external modules build with `W=1`.
- `g6ts_biosref.c` and `spi-geni-qcom.c` pass checkpatch with no errors or
  warnings.
- The safe 7.1.3, Phase 63, and Phase 64 boot artifacts are not modified.

## Isolated deployment checkpoint

The matched client and controller were embedded byte-for-byte in a new
initramfs. The older root-filesystem modules were restored immediately after
assembly, so only the dedicated GRUB entry selects Phase 65.

```text
entry id: sp11-phase65
command-line marker: sp11_entry=7.1.1-phase65
Phase 65 client source version: F1FB5433A889653756034F7
Phase 65 controller source version: 3FAD9771148895A06E6A06E
installed Phase 63 client source version: 2720A95296AB755A5FD2695
installed noisy controller source version: DB3C77C8E873D6BBA8925E8

27fab244985478ad819a68f8e49ea4ff5bd42f5205a6af6953d219c2e384fb0a  initrd.img-7.1.1-sp11-gpicmp1+-phase65
fcefdc928b6e45a8212722c9132b9da2dc1c197fc4890f7a9bab3c31d1584b94  sp11-7.1.1-phase65-hybrid.dtb
6f263da75052c54b16d9be21b315beab6b45a2c27c08710d5362b033b4aebf30  vmlinuz-7.1.1-sp11-gpicmp1+
```

The safe 7.1.3 saved default remains unchanged. Live fast-keyboard and ghost
validation remains required before Phase 65 is published.
