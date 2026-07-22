# Phase 88 hardware result: Linux initialization, invalid all-ones header

## Result

Phase 88 booted on the target SP11 on 2026-07-22. No physical panel contact
occurred before collection. The boot parameters and live module parameters
confirmed:

- Linux generic GENI initialization and mode selection were enabled;
- the captured Windows QGPI ring geometry was enabled;
- Linux's bidirectional QSPI `LINK` coupling was enabled;
- the Windows upper chronology, bounded CFU no-update path, and gated Heat
  continuation were enabled.

All three bounded hardware attempts completed their paired DMA transfer, but
the reset-response header was exactly:

```text
last_header=ff ff ff ff
last_class=255
last_content_id=255
last_content_len=0
initialization_stage=reset-response
quiesced_empty_reads=3
recovery_failures=3
irq_transport_errors=0
irq_protocol_errors=0
```

The nine-line filtered controller/client log has SHA-256:

```text
c27c34b607356eb18dafe04c35eed1f9baba43764b1a9b3dd61ab35b74fdc727
```

## Interpretation

The result rules out the missing generic GENI initialization/mode selection as
a sufficient explanation for Phase 87. It also proves the failure is still
before descriptors, feedback, CFU, Heat, and physical touch input.

The normal Linux SP11 QSPI path already contains a Linux-integrated version of
the same 13 preparation writes recovered from KDNET. Phase 88 therefore
compared the surrounding generic initialization, literal-versus-read/modify
DMA-mode programming, and the Windows guard; it did not remove all 13 writes.

Phase 89 keeps this controller path and the complete upper chronology but
restores Phase 75's normal Linux channel/event ring sizes. That isolates the
remaining lower-stack difference at the failing reset read.
