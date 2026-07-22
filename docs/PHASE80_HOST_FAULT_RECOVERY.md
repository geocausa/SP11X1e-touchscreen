# Phase 80 bounded host-fault recovery

Phase 80 is an isolated robustness experiment over the Phase 77 behavior and
recovery profile. It leaves the Phase 75 transport, Phase 72 mode exchange,
Heat parser, classifier, tracker, and saved GRUB default unchanged.

## Problem closed by this phase

The IRQ thread previously stopped after any DMA, GPIO, header-sync, body-size,
or framing error. A transport error set `fatal_transport_error`, but no
recovery work was queued and `mode_enabled` remained true. With an
edge-triggered GPIO51 interrupt, returning after the fixed drain limit could
also strand unread responses without another falling edge. Either path could
leave a touchscreen permanently silent until reboot.

Windows' captured host-timeout path instead resets and re-enumerates the
device. Phase 80 implements the Linux equivalent using only the existing,
hardware-proven cold recovery path.

## Opt-in behavior

`mshw0485_touch.host_fault_recovery=1` causes an IRQ read fault to:

1. classify and count transport versus protocol errors;
2. gate Linux input and release all active contacts;
3. record the exact negative error code;
4. select the full hardware power/reset recovery path; and
5. queue the ordinary bounded recovery worker.

The fresh attempt clears the old transport-fatal latch. If the new attempt
itself encounters another fatal transport error, the existing worker limit
still stops it; Phase 80 does not create an unbounded reset loop.

The ordinary IRQ drain is independently bounded at 128 responses. If GPIO51
still reports unread data after that boundary, the driver records an
`irq_drain_overflows` event and uses the same host-fault path. This avoids
silently abandoning an edge-triggered stream.

New read-only diagnostics are:

```text
host_fault_recoveries
irq_transport_errors
irq_protocol_errors
irq_drain_overflows
last_host_fault
```

They are separate from `panel_resets`, so a host-side failure cannot be
misreported as a spontaneous panel reset.

## Deliberately unchanged protocol

Phase 80 does not enable the one-byte Phase 79 SetFeature experiment and does
not replay a static full report `0x09`. The returned captures prove five
different complete report-`0x09` payloads with lifecycle-dependent fields;
their producer is not yet recovered. The empirical Phase 72 `{01,02}` plus
short-`0x09` sequence therefore remains the control.

The dedicated entry is `sp11-phase80-host-recovery`. Deployment creates a
new initramfs and arms that entry for one boot only. It never overwrites the
Phase 75 production assets or changes the saved default.

## Offline validation

- all 140 parser, classifier, tracking, lifecycle, output-policy, capture, and
  source-invariant tests pass;
- the complete client/controller/GPI module set builds without warnings using
  the exact GCC-configured `7.1.3-sp11-baseline1+` tree;
- Sparse reports no findings for all three modules;
- strict kernel style review reports zero errors, warnings, or checks;
- the new capture parser reproduces all five complete report-`0x09` variants
  from the archived/returned logs; and
- the Phase 80 client source version is `810D5D8DD456674DF996793`.

Hardware boot, deliberate fault injection, and recovery validation remain
required before this profile can be promoted.
