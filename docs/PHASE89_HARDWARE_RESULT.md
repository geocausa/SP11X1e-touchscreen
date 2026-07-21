# Phase 89 hardware result: Phase 75 transport still returns all ones

## Result

Phase 89 booted on the target SP11 on 2026-07-22 without physical panel
contact. Live parameters confirmed that all three lower-stack overrides were
disabled:

```text
spi_geni_qcom.sp11_windows_se_init=N
gpi.sp11_windows_ring_layout=N
gpi.sp11_qspi_linux_link=N
```

The controller therefore used the complete Phase 75 Linux transport: generic
GENI initialization, the Linux-integrated SP11 QSPI preparation, normal Linux
GPI ring sizes, and normal automatic bidirectional `LINK` behavior.

All three reset reads completed but returned the same result as Phase 88:

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
82e61f8499bf07f4bc7f3ea47637b8ee27e0a59a80f6b868b9675d5fd2a6588d
```

## Interpretation

Captured Windows ring geometry is not the cause of the invalid reset header.
The failure remains before descriptors and every upper-layer operation.

The remaining pre-request difference from Phase 75 is power/reset ordering.
The parity path reproduces `_PS0` followed by `_RST`, which releases reset,
asserts it again, then releases it a second time. Phase 75 uses one reset
release and a 300 ms settling delay. Phase 90 changes only this boundary.
