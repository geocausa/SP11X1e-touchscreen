# Multitouch roadmap

The current UEFI-derived path intentionally implements the firmware's simple
absolute-pointer report. Windows ETW evidence now proves that multitouch uses a
separate Capacitive Heat Map Digitizer collection, rather than a larger form of
the UEFI report. See [WINDOWS_HEAT_PROTOCOL.md](WINDOWS_HEAT_PROTOCOL.md).

## Proposed sequence

1. Add an opt-in HEAT diagnostic mode without changing the default report
   `0x40` path.
2. Retrieve and validate the device's HID report descriptor from Linux.
3. Accept and retain complete report `0x12`/3,636-byte frames in a bounded
   diagnostic ring.
4. Correlate labeled ETW gestures with the repeated `0x44`-byte sensor regions.
5. Determine whether a usable contact summary exists in the frame footer or
   whether Linux needs a heat-map tracker.
6. Add malformed and truncated frame tests before enabling input reporting.
7. Introduce Linux multitouch slots only after contact IDs and lifetimes are
   confirmed.
8. Preserve the existing single-touch decoder as a fallback.
9. Test contact addition, removal, crossing paths, palm interaction, suspend
   and resume.

## Non-goals

- No touchscreen firmware flashing.
- No calibration-storage unlock.
- No pen path until normal multitouch is stable.
- No assumption that Windows GPI-DMA framing matches the UEFI FIFO path.
