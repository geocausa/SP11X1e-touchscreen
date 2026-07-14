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

## Remaining work

1. Replace fixed thresholding with adaptive noise and edge compensation.
2. Split nearby or merged fingers reliably.
3. Add palm rejection, contact shape, pressure, and confidence reporting.
4. Decode the pen path without regressing finger input.
5. Validate rotation, suspend/resume, long-duration use, and multiple panels.
6. Rebase the controller and DMA changes onto newer kernel releases.
7. Refactor laboratory diagnostics into an upstream-reviewable architecture.

## Non-goals

- No touchscreen firmware flashing.
- No calibration-storage unlock.
- No claim of pen support until it is independently decoded and validated.
- No assumption that Windows GPI-DMA framing matches the UEFI FIFO path.
