# Phase 91: measured Windows response cadence

Phase 91 is Phase 90 plus one read-only option:

```text
mshw0485_touch.windows_read_cadence=1
```

It preserves the complete Phase 75 transport and power/reset path, Windows
upper chronology, bounded CFU inventory, Heat processing, contact profile, and
recovery safeguards.

The option changes only response consumption:

1. wait 490--550 microseconds between a valid four-byte header and its body;
2. service one complete response per threaded interrupt instead of treating a
   still-asserted GPIO51 level as proof that another header is immediately
   available.

Those bounds come directly from the stable 1,381-frame Windows SPB trace. The
Windows trace never begins the next Heat header within 2.735 ms of the previous
body, while the Phase 90 Linux loop could do so immediately. A separate
read-only analyzer reproduces the distribution from the private CSV.

This is a transport-scheduling adaptation, not a new panel command. Phase 75
remains the saved default, and Phase 90 remains preserved as the failing
control.

## First hardware boot

The first Phase 91 boot on 2026-07-22 completed the full initialization
chronology untouched, then survived rapid two-hand on-screen typing and
multi-touch use. The final pre-reboot snapshot recorded:

```text
heat_frames=8638
heat_errors=0
panel_resets=0
host_fault_recoveries=0
irq_transport_errors=0
irq_protocol_errors=0
irq_drain_overflows=0
cadence_single_response_irqs=8652
ready_verification_failures=0
```

Phase 90 had desynchronized after 1,984 Heat frames and then produced six
panel resets. Phase 91 therefore exceeded the Phase 90 failure point by more
than four times without a fault. This is strong evidence for the read-cadence
cause, but an immediate-login cold-boot stress test is retained as a second
independent attempt to reproduce the former early storm.

SHA-256 of the filtered controller/client log at the final snapshot:

```text
cafdc38b885d72818678d58a1b2dffb7613f366726e543d1924ad9f812f28cd8
```
