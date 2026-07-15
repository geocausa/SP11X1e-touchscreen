# Surface Pro 11 X Elite touchscreen driver

Experimental Linux support for the `MSHW0485` G6 touchscreen in the OLED
Microsoft Surface Pro 11. The repository preserves two isolated paths: the
working UEFI-derived FIFO/single-touch baseline and the hardware-validated
QSPI/GPI-DMA multi-touch experiment.

## Stable baseline: Phase 52

- Power and reset sequencing works.
- Qualcomm GENI protocol 9 transport works in the UEFI-derived FIFO mode.
- The controller completes the class-3/class-7 readiness exchange.
- Active-low GPIO51 gates input reads at the firmware's 5.3 ms interval.
- Normal class-1 touch and release reports work across the full display.
- Coordinates are normalized from 0 through 1023 on both axes.
- Linux identifies the device as a direct touchscreen.
- Live validation completed with no transport, protocol, readiness or GPIO
  errors.

## Experimental milestone: Phase 55

Phase 55 implements the panel's raw-heatmap personality with a matched GENI
QSPI and GPI-DMA stack. On a Surface Pro 11 OLED it has produced working
multi-touch, including confirmed two-finger pinch and zoom. Cold startup and
class-3 panel-reset recovery are automatic and bounded. Finger tracking has
also been validated with the desktop's three-finger window gesture. See
[phase55/README.md](phase55/README.md) and
[docs/PHASE55_DMA_MULTITOUCH.md](docs/PHASE55_DMA_MULTITOUCH.md).

The subsequent offline hardening pass makes successful DMA transfers quiet,
hides manual laboratory controls unless explicitly enabled at module load,
rejects malformed overlapping Heat blocks in the analysis tools, adds
synthetic parser/contact tests, and regression-checks the complete 1,381-frame
Windows corpus. See
[docs/PHASE56_OFFLINE_HARDENING.md](docs/PHASE56_OFFLINE_HARDENING.md).

Phase 57 replaces the earlier guessed adaptive detector with the recovered
Windows fixed-threshold, four-connected candidate extractor. Phase 58 adds
predicted-position global assignment, finite match gating, explicit track
lifecycle state, and the recovered exponential smoothing form. See
[docs/WINDOWS_TOUCH_DETECTOR_RE.md](docs/WINDOWS_TOUCH_DETECTOR_RE.md),
[docs/WINDOWS_TOUCH_TRACKER_RE.md](docs/WINDOWS_TOUCH_TRACKER_RE.md), and
[docs/PHASE58_TRACKING_PIPELINE.md](docs/PHASE58_TRACKING_PIPELINE.md).

Phase 59 adds the exact project-0x0c83 firmware NSR-bin gate: bounded parsing
of metadata record `0x04`, its 46-row to 16-bin mapping, and Windows' strict
cutoff of 655. The full Windows corpus reaches only 2, so this fidelity port
does not reject any established contact. See
[docs/PHASE59_NSR_METADATA.md](docs/PHASE59_NSR_METADATA.md).

The next Windows stage is now bounded as a ten-feature, four-score statistical
shape classifier with temporal class processing. Its architecture and decoded
subsection layout are documented. Phase 61 adds the recovered covariance-axis
and normalized-spread features to the offline tracer. Phase 62 proves the PSDB
pointer path and adds a bounded extractor/scorer for a locally supplied DLL,
without committing Microsoft data. Live filtering remains deferred until all
ten inputs, class labels, and labelled captures are available. See
[docs/PHASE60_CLASSIFIER_BOUNDARY.md](docs/PHASE60_CLASSIFIER_BOUNDARY.md) and
[docs/PHASE61_OFFLINE_GEOMETRY.md](docs/PHASE61_OFFLINE_GEOMETRY.md), and
[docs/PHASE62_PSDB_MODEL_EXTRACTOR.md](docs/PHASE62_PSDB_MODEL_EXTRACTOR.md).

The Phase 59 client was subsequently built, installed, and cold-boot validated
from the dedicated Phase 62 checkpoint entry on the experimental
`7.1.1-sp11-gpicmp1+` kernel. The validated boot used the already proven Phase
58 controller and GPI modules; only the touchscreen client changed. See
[docs/PHASE62_DEPLOYMENT.md](docs/PHASE62_DEPLOYMENT.md).

Phase 63 removes the laboratory-only raw command surface from the client,
adopts standard touchscreen properties and strict IRQ/PM error handling, and
adds a Windows-informed tentative-track output gate. Reverse engineering now
proves the five-state lifecycle, ten-entry class history, final output gate,
and transition-specific history windows. Linux uses independently written
three-, five-, and eight-frame quality bands to suppress the transient nearby
split candidate observed in the live one-finger trace. See
[docs/PHASE63_WINDOWS_LIFECYCLE.md](docs/PHASE63_WINDOWS_LIFECYCLE.md).
The client-only build passed a short live one-finger/multitouch validation and
is preserved in its own `sp11-phase63` GRUB entry; Phase 62 and the safe 7.1.3
entry remain available for rollback.

It is not yet production- or upstream-ready. Conservative broad-contact palm
filtering remains while later shape classification still needs more recovery
and labelled palm captures. Measured edge calibration, pressure, merged-contact
separation, suspend/resume, and broader kernel compatibility remain open. Pen
support is deliberately out of scope.

## Repository layout

```text
Kbuild
src/g6ts_biosref.c
src/spi-geni-qcom.c
include/linux/spi/spi-geni-qcom-biosref.h
dts/x1-microsoft-denali.dtsi
docs/BUILD.md
docs/PROTOCOL.md
docs/TESTING.md
docs/MULTITOUCH.md
docs/WINDOWS_HEAT_PROTOCOL.md
docs/PHASE54_GPI_DMA.md
docs/PHASE55_DMA_MULTITOUCH.md
docs/WINDOWS_TOUCH_DETECTOR_RE.md
docs/WINDOWS_TOUCH_TRACKER_RE.md
docs/PHASE58_TRACKING_PIPELINE.md
docs/PHASE59_NSR_METADATA.md
docs/PHASE60_CLASSIFIER_BOUNDARY.md
docs/PHASE61_OFFLINE_GEOMETRY.md
docs/PHASE62_PSDB_MODEL_EXTRACTOR.md
docs/PHASE62_DEPLOYMENT.md
docs/PHASE63_WINDOWS_LIFECYCLE.md
phase55/
tools/analyze_spb_etw_csv.py
tools/decode_heat_frame.py
tools/extract_windows_classifier.py
tools/regress_heat_frames.py
tools/track_heat_contacts.py
tests/test_heat_decoder.py
tests/test_contact_tracker.py
tests/test_windows_classifier.py
packaging/initramfs-tools/hooks/sp11-g6ts
```

`spi-geni-qcom.c` is based on the exact Ubuntu Concept controller source and
adds the isolated BIOS-reference transfer helper required by this device.

## Safety and scope

This repository does not contain Microsoft firmware, EFI binaries, firmware
updates, captures, boot images or initramfs files. The driver does not flash
the touchscreen and contains no CFU or FRU-unlock path. The GPI-DMA
experiments are isolated under `phase54/` and `phase55/`.

Use a separate boot entry and retain a known-good kernel. See
[docs/BUILD.md](docs/BUILD.md) and [docs/TESTING.md](docs/TESTING.md).
The client now has conventional suspend/resume callbacks, but platform suspend
remains unvalidated and disabled on the tested system after earlier
whole-device crashes.

## Tested hardware

- Microsoft Surface Pro 11 OLED
- Snapdragon X Elite / `x1e80100`
- Touch device `MSHW0485`
- QUP1 SE2 at `0x0a88000`
- Ubuntu Concept kernel `7.0.0-32-qcom-x1e`
- Experimental kernel `7.1.1-sp11-gpicmp1+` for Phase 55

## License

GPL-2.0. See [LICENSE](LICENSE). Individual files retain their SPDX notices.
