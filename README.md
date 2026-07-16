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
lifecycle state, and a conservative Linux-fitted coordinate filter. Later
Phase 69 analysis proves that the Windows tracker copies X/Y directly and that
its exponential blend applies to a separate component metric. See
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

Phase 64 completes the three peak-relative secondary detector passes and the
two-ring halo-energy feature, then evaluates the recovered four-score panel
profile in kernel-safe Q20.12 arithmetic. The fixed-point winner matches the
floating-point oracle for every one of the 1,113 contacts in the Windows
corpus. Only Windows output-allowed classes build tentative-track evidence;
confirmation remains sticky so one anomalous shape frame cannot make a real
finger flicker. See
[docs/PHASE64_FIXED_POINT_CLASSIFIER.md](docs/PHASE64_FIXED_POINT_CLASSIFIER.md).

Phase 65 targets fast on-screen-keyboard input. A paired raw-detector/input
trace proves that the fixed-point classifier takes only 55 microseconds at
the median and does not lose the reproduced taps. The isolated Phase 65 image
replaces a noisy bring-up controller artifact whose successful DMA transfers
were still logged at `INFO` level, and admits strong classifier-approved
touches after two frames while retaining the longer weak/split anti-ghost
windows. See
[docs/PHASE65_KEYBOARD_LATENCY.md](docs/PHASE65_KEYBOARD_LATENCY.md).

Phase 66 identified repeated class-3 panel resets as the cause of the remaining
keyboard pauses, but its cold-start replay mixed a complete ETW trace with a
second report-09 pair seen only in a partial KD recovery capture. The hardware
timed out at that added stage and did not start touch.

Phase 67 removed the unsupported second report-09 pair and passed a complete
static audit, but its first hardware boot still stopped after the report-0x73
exchange: no Heat frame followed. A control boot proved that the Phase 65
transport and minimal mode-entry sequence still worked on the same machine.

Phase 68 therefore removes the Windows collection/application setup from the
kernel reset path and restores the seven-stage sequence already validated by
Phase 55 through Phase 65. It retains the Phase 67 uninitialized-slot fix,
DMA failure cleanup, ACPI error propagation, classifier, tracking, and parser
hardening. Ghidra and import-table checks confirm that the Windows
TouchPenProcessor component is a processing library, not the HID-SPI
transport owner. The dedicated Phase 68 entry has now cold-booted successfully
on the target Surface, initialized after one bounded recovery, and delivered
working touch with active GPIO51 interrupts. See
[docs/PHASE68_PROVEN_RECOVERY.md](docs/PHASE68_PROVEN_RECOVERY.md).

Phase 69 freezes that hardware-proven driver while reconstructing the missing
Windows post-detector policy offline. It now extracts all 20 class-transition
records, exact context-window and output-code override parameters, association
radii, point-count limits, and output-merge distances from an operator-supplied
DLL. Testable helpers cover direct X/Y kinematics, strict scaled assignment,
far-edge snapping, the ordered three-branch output override, and chained
duplicate-output merging. No Phase 69 behavior has been deployed yet; kernel
replacement remains deferred until the remaining external flag provenance and
special/release output branches are proven. See
[docs/PHASE69_WINDOWS_PROCESSING_PARITY.md](docs/PHASE69_WINDOWS_PROCESSING_PARITY.md).

It is not yet ready for a mainline submission. Labelled palm and physical-edge
captures, measured edge calibration, pressure, merged-contact separation,
suspend/resume hardware validation, and broader kernel compatibility remain
open. Pen support is deliberately out of scope.

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
docs/PHASE64_FIXED_POINT_CLASSIFIER.md
docs/PHASE65_KEYBOARD_LATENCY.md
docs/PHASE66_WINDOWS_RECOVERY.md
docs/PHASE67_STATIC_AUDIT.md
docs/PHASE68_PROVEN_RECOVERY.md
docs/PHASE69_WINDOWS_PROCESSING_PARITY.md
phase55/
tools/analyze_spb_etw_csv.py
tools/decode_heat_frame.py
tools/extract_windows_classifier.py
tools/extract_windows_lifecycle.py
tools/windows_tracking_geometry.py
tools/regress_heat_frames.py
tools/track_heat_contacts.py
tests/test_heat_decoder.py
tests/test_contact_tracker.py
tests/test_windows_classifier.py
tests/test_windows_lifecycle.py
tests/test_windows_tracking_geometry.py
tests/test_source_invariants.py
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
