# Phase 84 hardware result: exact Windows GO stalls Linux RX

## Result

The isolated Phase 84 entry booted on the target SP11 on 2026-07-21. It
applied the recovered 13-write Windows serial-engine initialization, captured
Windows QGPI ring geometry, and exact Windows bidirectional GO flags without
Linux's `LINK` bit.

The first HID-SPI read pair then timed out before the reset response:

```text
SP11: applied exact Windows QSPI cold SE init sequence
SP11: QSPI combining HID read tx_len=8 rx_len=4
SP11: paired DMA sync map tx:ac0000.geniqup/1 rx:ac0000.geniqup/1
SPI RX transfer timed out
touch controller initialization failed path=hardware
stage=reset-response ret=-110 failures=1
```

SHA-256 of those five timestamped `dmesg -T` lines:

```text
dbd8ee4b69dc82b00ded9ba450aaebe783b98743af8b753c6826c72724e4f269
```

The frozen driver counters were:

```text
initialization_stage=reset-response
mode_enabled=0
heat_frames=0
panel_resets=0
recovery_successes=0
recovery_failures=1
hardware_recovery_attempts=1
irq_transport_errors=0
irq_protocol_errors=0
```

This failure precedes descriptors, A1/A5 feedback, device configuration, CFU,
and Heat. Input gating cannot have caused it.

## Interpretation

The result localizes the failure to the Linux controller/GPI integration at
the first bidirectional transfer. It is consistent with the already observed
Linux requirement: without `LINK` in the QSPI GO TRE, the pre-doorbelled RX
ring does not advance. Windows can omit that bit because its qcspi/qcgpi
channel contexts are coupled differently.

Phase 84 changed serial-engine initialization, ring geometry, and GO flags as
one exact lower-stack profile, so this single run does not prove by itself
that `LINK` is the only difference. The next strict comparison retains the
Windows initialization and ring geometry and changes only the Linux-visible
GO coupling at the failing transfer. Passing that comparison would isolate
the cause much more strongly.

Phase 84 remains installed as the immutable exact-Windows control. Phase 75
remains the saved working default.
