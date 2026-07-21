# Phase 88: Linux GENI initialization with Windows upper chronology

Phase 88 isolates the remaining Phase 87 reset-header failure. It changes one
active lower-stack axis:

```text
Phase 87: captured Windows 13-write GENI initialization
Phase 88: Linux GENI initialization and mode selection around the shared
          SP11 QSPI preparation writes
```

It retains:

- captured Windows QGPI channel/event ring sizes;
- Linux's required bidirectional QSPI `LINK` coupling;
- RX-before-TX submission and paired completion;
- Windows ACPI power/reset ordering;
- the complete Windows descriptor, feedback, configuration, and bounded CFU
  no-update chronology;
- gated admission into Phase 76 Heat processing;
- host-fault recovery and ready-line quiesce.

This is an operating-system integration experiment, not a byte-identical
Windows controller claim. If it returns a valid reset response, the Windows
serial-engine register profile—not Heat gating—was the remaining incompatible
lower-layer axis. If it still returns an invalid header, the captured ring
geometry or power/reset boundary remains for the next isolated comparison.

Clarification after the hardware boot: the production Linux SP11 QSPI helper
already programs a Linux-integrated form of the same 13 registers. Phase 88
restored generic `geni_se_init()` and `geni_se_select_mode()` and changed the
DMA-mode write/guard behavior; it did not remove every recovered register
write. The earlier phrase "restores Linux initialization" remains correct only
with that narrower meaning.

The client exports `last_header`, `last_class`, `last_content_id`, and
`last_content_len` in `behavior_stats`, so an empty or malformed result remains
observable even when ready-line quiesce correctly suppresses a false host
fault.
