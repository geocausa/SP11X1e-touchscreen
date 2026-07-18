# Multi-touch status and roadmap

The UEFI-derived path intentionally implements the firmware's simple
absolute-pointer report. Windows evidence proves that multi-touch uses a
separate Capacitive Heat Map Digitizer collection, rather than a larger form of
the UEFI report. Phase 55 now decodes that collection into Linux type-B
multi-touch slots. See [PHASE55_DMA_MULTITOUCH.md](PHASE55_DMA_MULTITOUCH.md).

## Completed in Phase 55

1. Retrieve and validate the 1,484-byte HID report descriptor.
2. Receive complete report-`0x12` frames through GPI DMA.
3. Decode the 68 by 46 sensor grid in Heat section `0x0100`.
4. Detect contact islands and expose up to ten Linux multi-touch slots.
5. Confirm two-finger input, pinch, and zoom on hardware.
6. Preserve the Phase 52 FIFO/single-touch path as a separate fallback.
7. Recover automatically after a class-3 panel reset.
8. Confirm three simultaneous fingers through a desktop window gesture.
9. Adapt the detection baseline independently on every Heat frame.
10. Add conservative broad-contact palm filtering, coordinate smoothing, and
    one-frame contact-dropout protection.

## Remaining work

1. Add measured edge compensation after a repeatable corner-tap calibration.
2. Split nearby or merged fingers reliably.
3. Add contact shape, pressure, and confidence reporting where the Heat data
   supports them.
4. Validate rotation, long-duration use, and multiple panels.
5. Rebase the controller and DMA changes onto newer kernel releases.
6. Refactor the remaining laboratory diagnostics into an upstream-reviewable
   architecture.

## Non-goals

- No touchscreen firmware flashing.
- No calibration-storage unlock.
- No pen support; this driver is intentionally finger-only.
- Suspend/resume callbacks exist, but platform suspend remains unvalidated and
  is not claimed safe on the tested machine.
- No assumption that Windows GPI-DMA framing matches the UEFI FIFO path.
