# Phase 89: Phase 75 transport with Windows upper chronology

Phase 89 restores the complete hardware-proven Phase 75 lower transport while
retaining the recovered Windows initialization above the SPI boundary.

Relative to Phase 88, it disables the captured 16-entry channel and 32-entry
event rings. The default Linux GPI driver instead allocates its normal 64-entry
channel rings and normal event ring, and automatically applies its established
bidirectional QSPI `LINK` behavior. It also retains Linux generic GENI
initialization and mode selection.

The following upper-layer behavior is unchanged from Phase 88:

- Windows ACPI power/reset ordering;
- descriptor, A1/A5 feedback, device configuration, and bounded CFU no-update
  chronology;
- gated admission to ordinary Heat processing;
- Phase 76 contact behavior;
- host-fault recovery and ready-line quiesce;
- no firmware payload path.

If the reset header becomes valid, the Windows-sized GPI rings were
incompatible with this Linux channel implementation. If `ff ff ff ff` remains,
the next isolation boundary is the power/reset ordering rather than Heat or
contact processing.

Phase 89 is a one-shot laboratory boot. Phase 75 remains the saved default.
