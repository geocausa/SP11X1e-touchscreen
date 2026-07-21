# Phase 90 hardware result: full chronology reaches Heat, read cadence fails

## Untouched initialization

Phase 90 booted on the target SP11 on 2026-07-22. With no physical contact it
completed every gated stage:

- valid reset response and both descriptors;
- early feature `0x73 = fe ff` and feature `0x06` capabilities;
- provider-built A1/A5 feedback;
- device configuration and report `0x56` identity;
- bounded CFU no-update inventory;
- final feature `0x73 = 90 01`;
- admission to `wait-heat` with zero resets and zero errors.

This proves the Phase 75 power/reset sequence is required by the Linux
integration and that the complete recovered upper chronology can activate
Heat.

## Active-touch result

The first physical test produced 1,984 valid Heat frames. Only 156 ms after the
first valid frame, the IRQ drain immediately attempted another header while
GPIO51 was still asserted and received:

```text
invalid HID-SPI header=2e c1 c8 23 ready=1
```

One host recovery succeeded. Six genuine panel reset notifications then
occurred under active Heat traffic, with every bounded recovery completing.
Once contact stopped, a 15-second observation produced no further Heat frames
or resets. Final counters included:

```text
heat_frames=1984
heat_errors=0
panel_resets=6
recovery_successes=8
recovery_failures=0
host_fault_recoveries=1
irq_protocol_errors=1
```

SHA-256 of the complete filtered controller/client log is:

```text
8acc3086c9118499cf2ac04533b4c8cfde91b777cd6f4bfaa1849aeeaa9fbf22
```

## Windows cadence cross-check

The read-only May SPB CSV has SHA-256
`0209583a33f180bf7cd76d17c90ba16da3a37a93921253c2e667af40ebcb1514`.
Across all 1,381 complete Heat responses:

```text
header RX -> body TX: n=1381, min=490.0 us, median=504.8 us
body RX -> next Heat header TX: n=1380, min=2735.0 us, median=7828.3 us
next-header gaps below 1 ms: 0
```

Linux did neither: it issued the body immediately, then allowed its level test
to chain a second header from the still-asserted ready line. Phase 91 changes
only this response cadence.
