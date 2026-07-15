# Multitouch roadmap

The current UEFI-derived path intentionally implements the firmware's simple
absolute-pointer report. Future multitouch work should preserve that known-good
path while adding diagnostics before interpreting new packet layouts.

## Proposed sequence

1. Capture every distinct class-1 body length and content ID during two- and
   three-finger interaction.
2. Retain complete raw bodies in a bounded diagnostic ring.
3. Determine contact count, contact identifier, tip state and X/Y field
   boundaries from repeated captures.
4. Add malformed and truncated packet tests before enabling input reporting.
5. Introduce Linux multitouch slots with `input_mt_init_slots()` and
   `input_mt_slot()` only after contact IDs are confirmed.
6. Preserve the existing single-touch decoder as a fallback.
7. Test contact addition, removal, crossing paths, palm interaction, suspend
   and resume.

## Non-goals

- No touchscreen firmware flashing.
- No calibration-storage unlock.
- No pen path until normal multitouch is stable.
- No assumption that Windows GPI-DMA framing matches the UEFI FIFO path.
