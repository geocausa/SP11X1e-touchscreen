# Phase 87 hardware result: LINK completes DMA, header remains invalid

## Result

Phase 87 booted on the target SP11 on 2026-07-22 without physical panel
contact. It retained the recovered Windows serial-engine initialization and
ring geometry, but added Linux's `LINK` bit to each bidirectional QSPI GO.

Unlike Phase 84, the first RX DMA did not time out. All three bounded hardware
attempts completed far enough for the ready-line quiesce path to classify the
returned four-byte header as invalid after GPIO51 deasserted:

```text
initialization_stage=reset-response
recovery_failures=3
hardware_recovery_attempts=3
quiesced_empty_reads=3
panel_resets=0
irq_transport_errors=0
irq_protocol_errors=0
```

The client returned `-EAGAIN` on each attempt rather than Phase 84's
`-ETIMEDOUT`. SHA-256 of the filtered controller/initialization log is:

```text
50afd0408b3bd6a89770da8c594aee78ab33e5a9ebd524785aea69f7171232c9
```

## Interpretation

This proves that restoring `LINK` crosses the Phase 84 Linux RX-completion
failure. It does not yet produce a valid HID-SPI reset header, so the remaining
boundary precedes descriptors, feedback, CFU, and Heat.

The next comparison keeps the captured QGPI ring geometry and Linux `LINK`,
but restores Linux's hardware-proven GENI initialization and mode selection.
That changes one active lower-stack variable at the failing transfer. It also
exports the exact last four header bytes in `behavior_stats`.

Touch input never opened in Phase 87, so lack of physical panel contact cannot
explain the result.
