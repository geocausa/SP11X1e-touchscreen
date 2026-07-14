# Phase 55: DMA heatmap to Linux multi-touch

## Recovered processing path

Windows registers `TouchPenProcessor0C83.dll` as the Heat software processor
for `HID\\MSHW0485&Col02`. The DLL consumes raw Heat frames and implements
full-frame parsing, blob detection, tracking, palm rejection, and conversion
to finger and pen input.

Linux receives the same report `0x12` container through the Phase 55 QSPI/GPI
DMA transport. The current implementation performs the smallest useful open
replacement:

1. Parse the Heat container and length-prefixed sections.
2. Select section `0x0100`, mode 1, header value 8.
3. Reassemble exactly 3,128 samples into a 68 by 46 grid.
4. Find the modal per-frame baseline, normally `0xb4` or `0xb5`.
5. Mark samples at least eight levels below the baseline.
6. Form eight-neighbour connected components of at least two samples.
7. Map weighted centroids to Linux coordinates from 0 through 32767.
8. Assign the ten strongest components to Linux multi-touch slots.

The `0xff00` section is retained as metadata but is not needed for the current
finger-centroid implementation. The 333-byte trailer outside the Heat
container is not interpreted.

## Reset recovery

After a sustained session the panel can emit a class-3 reset response. Replaying
only reports `0x05`, `0x70`, and `0x56` receives valid acknowledgements but does
not restart Heat frames. The validated recovery is:

1. Release all Linux contacts.
2. Power-cycle the panel through ACPI or its paired GPIOs.
3. Consume the spontaneous class-3 reset.
4. Retrieve the device descriptor and report descriptor.
5. Replay the proven mode exchange.
6. Re-enable interrupt-driven frame reads.

Recovery runs in delayed work, is bounded to three attempts, and stops on a
fatal transport error. The same path performs automatic cold startup.

## Evidence boundary

No Microsoft DLL, PDB, firmware blob, ETL capture, or raw user trace is
included in this repository. The implementation records only independently
derived protocol structure and Linux source code.
