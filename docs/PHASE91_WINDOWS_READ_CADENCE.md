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
