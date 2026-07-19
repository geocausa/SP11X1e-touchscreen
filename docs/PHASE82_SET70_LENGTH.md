# Phase 82 Windows-length SET70 experiment

Phase 82 is a cold-boot, single-axis comparison against Phase 81. It enables
the existing `feature70_one_byte=1` switch so that SET_FEATURE report `0x70`
has one logical content byte, `{01}`, matching the corrected live KDNET
transfer boundary.

The captured Windows write had `content_len=1` and `txLen=12`:

```text
8-byte HID-SPI body header + 1 content byte + 3 alignment bytes = 12
```

The three alignment bytes are clocked but are outside the logical HID content.
They do not support the retracted six-byte payload interpretation. Phase 72/75
instead sends the derived two-byte logical content `{01,02}`. Its empirical
benefit remains real but causally unexplained.

## Isolation boundary

Compared with Phase 81, Phase 82 changes only this SET70 logical length. It
retains:

- the Phase 75 GPI-DMA transport, DT, kernel, and short OUTPUT report `0x09`;
- Phase 76 contact behavior;
- Phase 77 bounded software reset recovery;
- Phase 80 bounded host-fault recovery; and
- Phase 81 GPIO51 trailing-read quiescence.

It does not enable the Phase 78 storm breaker, replay the cold-boot-only report
`0x65`, alter contact processing, or change recovery timing. A cold boot is
required because warm module reloads have repeatedly changed the panel's reset
behavior and cannot isolate startup configuration.

The saved Phase 75 GRUB default remains untouched. Deployment creates only the
one-shot `sp11-phase82-set70` entry.

## Warm initialization smoke test

The exact-tree Phase 82 client (`E6857F94A08401AE5EE35FB`) replaced Phase 81
through a live module reload. Hardware initialization completed with the
expected one-byte SET70 log, zero panel resets, zero host faults, and zero
transport/protocol errors during the initial quiescent observation. No touch
was applied, so this proves initialization only; the one-shot cold boot remains
the deciding comparison.
