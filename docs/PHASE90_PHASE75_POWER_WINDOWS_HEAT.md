# Phase 90: Phase 75 power/reset with Windows upper chronology

Phase 90 keeps the complete Phase 89 controller/GPI transport and recovered
Windows upper chronology. It changes only the cold power/reset selection:

```text
Phase 89: Windows-parity _PS0 followed by _RST ordering
Phase 90: hardware-proven Phase 75 power/reset sequence
```

The Phase 75 GPIO path holds reset low, enables power, waits 500 ms, releases
reset, and waits 300 ms. The Windows-parity path first performs the `_PS0`
release and then immediately performs another 300 ms `_RST` pulse. Both paths
are preserved; the read-only `parity_linux_power=1` option selects the Phase 75
sequence only for this laboratory boot.

All descriptor, feedback, configuration, bounded CFU, Heat, contact, and
recovery behavior remains identical to Phase 89. No firmware payload path is
present. Phase 75 remains the saved default.
