# Phase 55: DMA heatmap to Linux multi-touch

## Recovered processing path

Windows registers `TouchPenProcessor0C83.dll` as the Heat software processor
for `HID\\MSHW0485&Col02`. The DLL consumes raw Heat frames and implements
full-frame parsing, blob detection, tracking, palm rejection, and conversion
to finger and pen input.

Linux receives the same report `0x12` container through the Phase 55 QSPI/GPI
DMA transport. Phase 57 ports the DLL's first candidate-extraction stage and
uses explicit Linux fallbacks for its later proprietary tracker. The Ghidra
evidence and remaining boundary are recorded in
[WINDOWS_TOUCH_DETECTOR_RE.md](WINDOWS_TOUCH_DETECTOR_RE.md).

1. Parse the Heat container and length-prefixed sections.
2. Select section `0x0100`, mode 1, header value 8.
3. Reassemble exactly 3,128 samples into a 68 by 46 grid.
4. Keep the modal level (`0xb4` or `0xb5`) for diagnostics only.
5. Apply the Windows-derived absolute active ceiling of raw byte 171.
6. Form four-neighbour components; accept at least three samples, or a one- or
   two-sample component whose peak is at most raw byte 162.
7. Map weighted centroids to Linux coordinates from 0 through 32767.
8. Assign the ten strongest components to Linux multi-touch slots.
9. Reject only components broader than the conservative palm boundary.
10. Smooth small coordinate changes and bridge up to six missing frames as the
    current bounded stand-in for Windows track lifecycle handling.

The `0xff00` section is retained as metadata but is not needed for the current
finger-centroid implementation. The 333-byte trailer outside the Heat
container is not interpreted.

The candidate policy was checked against 1,381 saved Windows Heat frames. Every
frame decoded successfully; 1,113 frames contained an accepted contact, 268
were idle, and none crossed the conservative palm boundary. The largest
accepted fingertip occupied 11 samples, while the driver rejects only
components above 48 samples or spanning more than 12 rows or columns.

## Finger-only and power-management scope

Pen extraction is deliberately not implemented. The Linux input device reports
finger contacts only. Phase 55 originally contained no suspend/resume
callbacks; the current client has conventional callbacks, but platform suspend
remains unvalidated because earlier system-level suspend attempts crashed the
tablet. Automatic cold startup and bounded panel reset recovery remain fully
enabled.

The removed `dma_windows_output_sequence` experiment is not part of startup or
recovery and is no longer exposed through sysfs. It previously reproduced an
unsafe laboratory sequence and once caused a hard freeze.

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
