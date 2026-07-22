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

## Cold-boot result

The one-shot entry booted the intended kernel, client source version, and all
five intended switches. During the first 72 seconds it recorded 10 genuine
class-3 panel resets, seven safely quiesced trailing reads, and three persistent
invalid headers. Each invalid header was the identical `2e c1 c8 23`, arrived
44-220 milliseconds after input reopened following a reset recovery, and found
GPIO51 still asserted. Phase 80 therefore correctly performed three bounded
hardware recoveries. There were no transport errors, drain overflows, malformed
Heat frames, recovery failures, or ready-frame verification failures.

The last reset occurred at 71.869 seconds. At 277 seconds the driver had
processed 7,410 valid Heat frames without another reset or fault:

```text
panel_resets=10
host_fault_recoveries=3
irq_protocol_errors=3
quiesced_empty_reads=7
heat_frames=7410
heat_errors=0
recovery_successes=14
recovery_failures=0
```

This run recovered into sustained useful touch sooner than the Phase 81 cold
run, which had 24 resets through 119 seconds. One boot cannot establish that
the SET70 length caused the improvement, and Phase 82 was not a clean startup.
It remains an experiment rather than replacing the Phase 75 saved baseline.
The repeated post-recovery header is now a distinct diagnostic target; it must
not be silently classified as an empty trailing read while GPIO51 is asserted.
