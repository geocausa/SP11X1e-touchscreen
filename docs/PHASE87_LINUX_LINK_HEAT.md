# Phase 87: Windows parity with Linux RX coupling

Phase 87 is the direct comparison to the Phase 84 hardware failure. It keeps:

- the recovered Windows 13-write QSPI initialization;
- captured Windows channel and event ring sizes;
- RX-before-TX submission and doorbell ordering;
- the complete Phase 86 Windows init, bounded CFU no-update, and Heat path;
- Phase 76 Windows-derived contact processing;
- host-fault recovery and ready-line quiesce.

It changes one lower-stack property at the first failing transaction:

```text
gpi.sp11_qspi_linux_link=1
```

This adds `LINK` to a bidirectional QSPI GO while retaining the Windows ring
geometry. The resulting GO flags are Linux-adapted `0x00200901`, rather than
the exact Windows `0x00200101` tested by Phase 84. The adaptation is explicit
and read-only; it is not represented as byte-identical Windows behavior.

If the first reset-response read completes, the experiment has crossed the
precise Phase 84 failure boundary. Later terminal stages remain independently
observable through `behavior_stats`. Heat opens only after the complete
init+CFU chronology and the first structurally valid report `0x12`.

The entry is one-shot. Phase 75 remains the saved default, and Phase 84/86
remain unchanged as controls.
