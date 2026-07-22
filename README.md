# Surface Pro 11 X Elite touchscreen driver

Linux support for the `MSHW0485` G6 touchscreen in the OLED Microsoft Surface
Pro 11. The hardware-validated production baseline is Phase 91: QSPI/GPI-DMA
multi-touch on `7.1.3-sp11-baseline1+`, with the recovered Windows upper
initialization chronology and measured response cadence. Two cold boots,
including immediate login-screen stress, completed 14,950 Heat frames with no
reset, invalid header, or transport error. See
[docs/BASELINE_DMA_PHASE91.md](docs/BASELINE_DMA_PHASE91.md) and
[docs/STATUS.md](docs/STATUS.md) for the exact supported, experimental, and
unsupported boundaries.

> **Validation caveat:** Phase 91 has passed two cold boots and focused
> login/typing/multi-touch stress, but it has not yet completed an extensive
> multi-day real-world soak. It is the best current baseline for the tested
> OLED SP11 and exact kernel, not a universal stability claim. Keep both
> fallback entries.

The installed boot layout retains two rollback paths: the previous Phase 75 DMA
image and the 7.1.3 FIFO image. Historical experimental menu scripts are
archived during promotion, while their boot assets and repository recipes are
preserved. The deliberately resetting Phase 74 code is excluded from
production; only its negative result is documented.

Phase 76 is a separate, opt-in behavior experiment over the unchanged Phase 75
transport and recovery baseline. It combines recovered sensor-space
assignment, a bounded normal output-centroid branch, direct coordinates, and
the previously hardware-tested two-frame strong-contact gate. It remains a
one-shot GRUB test until live keyboard, edge, crossing-finger, and reset
validation is complete. See
[docs/PHASE76_BEHAVIOR.md](docs/PHASE76_BEHAVIOR.md).

An isolated `windows_init_parity` path now rebuilds cold bring-up independently
of Heat/contact processing. It validates the exact SP11 HID-SPI descriptor
identity, reconstructs Windows' initial A1/A5 feedback from explicit provider
state, and reproduces the device-config `0x05/0x70/0x56` exchanges. Touch input
remains deliberately disabled and the path stops before the independently
owned CFU `0x60/0x65` traffic. The installed CFU owner and its complete
no-update response path are now decoded for a later isolated checkpoint; they
do not alter Phase 84 and no firmware payload path is implemented. See
[docs/WINDOWS_INIT_PARITY.md](docs/WINDOWS_INIT_PARITY.md) and
[docs/WINDOWS_CFU_BOUNDARY.md](docs/WINDOWS_CFU_BOUNDARY.md). The matching
guarded QSPI controller initialization is documented in
[docs/WINDOWS_CONTROLLER_INIT_PARITY.md](docs/WINDOWS_CONTROLLER_INIT_PARITY.md).

Phase 86 preserves those input-disabled checkpoints but continues the complete
Windows init and bounded CFU no-update chronology into ordinary Heat
consumption. It enables the separately tested Phase 76 contact profile and
opens input only after every preceding response validates; no additional mode
command and no firmware payload are sent. See
[docs/PHASE86_WINDOWS_HEAT.md](docs/PHASE86_WINDOWS_HEAT.md).

The first Phase 84 hardware boot stopped at the initial reset-response RX
transfer: exact Windows GO flags did not advance Linux's pre-doorbelled RX
ring. Phase 87 retains the recovered Windows initialization and ring sizes but
adds the explicitly labelled Linux `LINK` coupling before continuing into the
same CFU/Heat path. See
[docs/PHASE84_HARDWARE_RESULT.md](docs/PHASE84_HARDWARE_RESULT.md) and
[docs/PHASE87_LINUX_LINK_HEAT.md](docs/PHASE87_LINUX_LINK_HEAT.md).

Phase 87 proved that `LINK` removes the DMA timeout, but the first completed
read still contained no valid reset header after the ready line deasserted.
Phase 88 keeps the Windows upper chronology and captured ring sizes while
restoring Linux's generic GENI initialization and mode selection. Its untouched
hardware boot completed with `ff ff ff ff`, so Phase 89 restores the remaining
Phase 75 lower-stack property: Linux's normal GPI ring geometry. Phase 89 also
returned `ff ff ff ff`, ruling out the lower transport; Phase 90 isolates the
power/reset ordering while retaining the complete upper chronology. Phase 90
completed that chronology and delivered 1,984 valid Heat frames, but an
immediate second header read desynchronized the stream and preceded six panel
resets. Phase 91 applies the cadence measured from 1,381 stable Windows frames.
Two Phase 91 cold boots, including immediate login-screen stress, processed
14,950 Heat frames with no panel reset, invalid header, or transport fault;
Phase 91 is therefore the promoted DMA baseline.
See
[docs/PHASE87_HARDWARE_RESULT.md](docs/PHASE87_HARDWARE_RESULT.md) and
[docs/PHASE88_LINUX_SE_WINDOWS_HEAT.md](docs/PHASE88_LINUX_SE_WINDOWS_HEAT.md),
[docs/PHASE88_HARDWARE_RESULT.md](docs/PHASE88_HARDWARE_RESULT.md), and
[docs/PHASE89_LINUX_TRANSPORT_WINDOWS_HEAT.md](docs/PHASE89_LINUX_TRANSPORT_WINDOWS_HEAT.md),
[docs/PHASE89_HARDWARE_RESULT.md](docs/PHASE89_HARDWARE_RESULT.md), and
[docs/PHASE90_PHASE75_POWER_WINDOWS_HEAT.md](docs/PHASE90_PHASE75_POWER_WINDOWS_HEAT.md),
[docs/PHASE90_HARDWARE_RESULT.md](docs/PHASE90_HARDWARE_RESULT.md), and
[docs/PHASE91_WINDOWS_READ_CADENCE.md](docs/PHASE91_WINDOWS_READ_CADENCE.md).

## Historical FIFO baseline: Phase 52

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
including the exact 68-by-46 panel factors, far-edge snapping, the ordered
three-branch output override, and chained
duplicate-output merging. Candidate boundary/corner flags and the pen-only
orientation source are now distinguished. No Phase 69 behavior has been
deployed yet; kernel replacement remains deferred until the remaining
context/region flag provenance and special/release output branches are proven. See
[docs/PHASE69_WINDOWS_PROCESSING_PARITY.md](docs/PHASE69_WINDOWS_PROCESSING_PARITY.md).

Phase 70 bakes the bounded geometry and base transition result into an opt-in
kernel frame profile. The client retains sensor-space centroids, uses the
recovered per-axis quantization and strict radius-five global assignment,
stores ten score vectors, applies all 20 base transition records, and directly
publishes matched X/Y without the Linux-only smoothing stage. Its load-time
switch is read-only and defaults off; the known-good Phase 68 behavior remains
the module default because later Windows lifecycle branches still require
provider-owned frame/context values not present in raw Heat reports. See
[docs/PHASE70_KERNEL_FRAME_ORCHESTRATOR.md](docs/PHASE70_KERNEL_FRAME_ORCHESTRATOR.md).

The first Phase 70 boot kept the panel, DMA transport, detector, and
multi-candidate extraction healthy but emitted no Linux contacts. Phase 71
uses live score vectors and Ghidra to close the cause: it ports the exact
`+0x4d/+0x4e` local-maximum producers and applies the recovered class-three
50/20 score adjustment before lifecycle admission. The corpus now computes
these fields directly with zero fixed-point or assignment mismatch. Phase 71
remains an isolated one-shot hardware experiment; see
[docs/PHASE71_SCORE3_PRODUCER.md](docs/PHASE71_SCORE3_PRODUCER.md).

Phase 72 closes the frequent class-3 panel-reset regression that Phases 66-68
narrowed but could not resolve. A live KDNET session against the shipping
Windows stack (Surface Pro 11, build 26100, resolved `hidspi.sys` PDB symbols)
confirmed that 63-byte report `0x09` participates in initialization and
host-reset/shallow-wake setup and that report `0x65` is cold-boot-only. A
natural panel-initiated reset was not captured. Phase 72 then
captured Linux's one-byte `GET_FEATURE 0x70` result (`02`), sent derived
`SET_FEATURE 0x70 = {0x01,0x02}`, and emitted short
`OUTPUT_REPORT 0x09 = {0x8e,0x02}`. The combined sequence produced zero panel
resets over a roughly six-hour session including deliberate stress, against a
prior baseline of one reset every 2-7 seconds under sustained touch.

The original analysis incorrectly claimed that Windows sent a six-byte feature
payload. Applying the capture's `txLen` and `content_len` proves that Windows'
logical `0x05` and `0x70` payloads are each the single byte `{0x01}`; the extra
displayed bytes were padding or lay beyond the transfer. Phase 72's hardware
result stands, but its causal mechanism is not isolated and its sequence is not
byte-for-byte Windows traffic. See
[docs/PHASE72_LIVE_KDNET_ROOT_CAUSE.md](docs/PHASE72_LIVE_KDNET_ROOT_CAUSE.md)
and [docs/PHASE72_KDNET_ERRATUM.md](docs/PHASE72_KDNET_ERRATUM.md).

The returned July lifecycle capture closes another concrete gap: Windows
actively resets and re-enumerates after a host-side HID-SPI timeout, whereas
the Linux IRQ reader could stop permanently on a transport, framing, or drain
failure. Phase 80 adds an isolated, bounded host-fault recovery using the
existing cold path and separate diagnostics; it deliberately retains the
Phase 72 mode exchange because five complete report-`0x09` variants contain
lifecycle-dependent fields. See
[docs/KDNET_20260718_LIFECYCLE_CAPTURE.md](docs/KDNET_20260718_LIFECYCLE_CAPTURE.md)
and [docs/PHASE80_HOST_FAULT_RECOVERY.md](docs/PHASE80_HOST_FAULT_RECOVERY.md).

An end-to-end audit of both July 18 sessions corrects the remaining scope:
none of the armed natural panel-reset breakpoints fired. The captured resets
were cold-start or host-timeout/debugger-perturbed paths, and the outgoing
setup writes came from several collection and lifecycle owners. A proposed
single static 63-byte report-`0x09` experiment was therefore discarded before
build or deployment. See
[docs/KDNET_20260718_FULL_SESSION_AUDIT.md](docs/KDNET_20260718_FULL_SESSION_AUDIT.md).

Static analysis of the matching ARM64 TouchPenProcessor now identifies the
report-`0x09` producer. The A1 packet is display-state feedback containing
display state, hinge angle, and a persistent FastHostId. The A5 packet is a
version-6 feedback-manager record containing a successful-send sequence,
validity bitmap, current provider data, and bytes retained from earlier rich
updates. The two captured `0x0190` fields are independently owned values that
happened to match. This rules out treating any captured A/B/C packet as a
fixed Windows mode command; see
[docs/WINDOWS_REPORT09_FEEDBACK_RE.md](docs/WINDOWS_REPORT09_FEEDBACK_RE.md).

The matching Microsoft CFU payload has also been safely unwrapped for static
analysis. Its ARC image contains the exact 1,484-byte HID descriptor read from
the live panel. The firmware version occurs in both GET report `0x60` and the
cold-only report `0x65`, identifying `0x65` as firmware-update management
traffic with high confidence rather than ordinary touch recovery. No firmware
is flashed or redistributed. See
[docs/TOUCH_FIRMWARE_UPDATE_RE.md](docs/TOUCH_FIRMWARE_UPDATE_RE.md).

The ARC tail is now decoded as a tagged resource container. Besides the exact
HID descriptor it contains a 274-command engineering description, a firmware
logger dictionary, and the compressed Denali panel configuration. These
resources independently confirm PRE_OS versus normal full-frame modes,
display/hinge/FastHostId feedback, on-device calibration/noise/tracking paths,
and the 68-by-46 sensor geometry. They do not yet prove that HID Feature
`0x70` is the report-mode selector; see
[docs/FIRMWARE_RESOURCE_CONTAINER.md](docs/FIRMWARE_RESOURCE_CONTAINER.md).

Phase 72 first delivered sustained multi-touch without the earlier class-3
reset storm, providing the control that led through Phase 75 to Phase 91. The
driver is still not ready for a mainline submission.
Labelled palm and physical-edge captures, measured edge calibration, pressure,
merged-contact separation, suspend/resume hardware validation, and broader
kernel compatibility remain open. Pen support is deliberately out of scope.

Phase 73 re-homes the full QSPI/GPI-DMA multi-touch stack and the Phase 72
sequence onto the `7.1.3` baseline kernel, retiring the `7.1.1`
`sp11-gpicmp1+` lab kernel as the working target. All three custom modules (client,
`spi-geni-qcom`, `gpi`) rebuild cleanly against `7.1.3` despite ~20-25% upstream
drift in the base controller sources. The baseline device tree carried the touch
node but was authored for FIFO and omitted the GPI-DMA channel wiring, which
caused the first DMA boot to time out at stage 1; adding `qcom,enable-gsi-dma`,
`dmas`, and `dma-names` to the `spi@a88000` node (matching the lab DTB) resolved
it. On `7.1.3-sp11-baseline1+` with the DMA device tree live, touch initialized
over GPI-DMA with no timeout, the Phase 72 combined exchange ran, and the panel
initialized with zero resets. At that point this was the furthest project
milestone: a working DMA multi-touch touchscreen on the intended baseline
kernel. It is not full Windows parity. Phase 75 subsequently became the first
saved DMA production baseline after separating the driver identity. See
[docs/PHASE73_BASELINE_DMA.md](docs/PHASE73_BASELINE_DMA.md) and
[dts/PHASE73_BASELINE_DMA_DTB.patch.md](dts/PHASE73_BASELINE_DMA_DTB.patch.md).

Phase 75 removes the remaining FIFO/DMA identity collision. The production DMA
client now builds as `mshw0485_touch.ko`, binds as `mshw0485-touch`, and uses
the `microsoft,mshw0485` DT compatible. The legacy UEFI/FIFO fallback retains
the historical `g6ts_biosref.ko` and `microsoft,mshw0485-biosref` identities.
This prevents `modinfo`, module parameters, aliases, and initramfs contents from
silently referring to different implementations under the same name. See
[docs/PHASE75_DRIVER_IDENTITY.md](docs/PHASE75_DRIVER_IDENTITY.md).
It has now booted successfully on the 7.1.3 baseline with the renamed client,
explicit DMA device tree, zero panel resets, zero transport errors, and normal
single- and multi-touch behaviour. Phase 75 is retained as the previous DMA
rescue image after the Phase 91 promotion; the FIFO baseline remains the final
rollback entry.

## Repository layout

```text
Kbuild
src/g6ts_biosref.c
src/spi-geni-qcom.c
phase55/modules/mshw0485_touch.c
phase55/modules/spi-geni-qcom.c
phase55/modules/gpi.c
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
docs/PHASE70_KERNEL_FRAME_ORCHESTRATOR.md
docs/PHASE71_SCORE3_PRODUCER.md
docs/PHASE72_LIVE_KDNET_ROOT_CAUSE.md
docs/PHASE72_KDNET_ERRATUM.md
docs/PHASE73_BASELINE_DMA.md
docs/PHASE75_DRIVER_IDENTITY.md
docs/PHASE76_BEHAVIOR.md
docs/PHASE77_GATED_RECOVERY.md
docs/PHASE78_RESET_STORM_BREAKER.md
docs/PHASE80_HOST_FAULT_RECOVERY.md
docs/PHASE81_READY_QUIESCE.md
docs/PHASE82_SET70_LENGTH.md
docs/BASELINE_DMA_PHASE91.md
docs/KDNET_20260718_LIFECYCLE_CAPTURE.md
docs/KDNET_20260718_FULL_SESSION_AUDIT.md
docs/TOUCH_FIRMWARE_UPDATE_RE.md
docs/FIRMWARE_RESOURCE_CONTAINER.md
phase55/
tools/analyze_spb_etw_csv.py
tools/decode_heat_frame.py
tools/extract_windows_classifier.py
tools/extract_windows_lifecycle.py
tools/generate_lifecycle_header.py
tools/extract_kdnet_hidspi.py
tools/extract_cfu_payload.py
tools/extract_firmware_resources.py
tools/ghidra/SeedArcFirmware.java
tools/ghidra/SearchStringXrefs.java
tools/ghidra/SearchAddressXrefs.java
tools/ghidra/SearchPointerEncodings.java
tools/ghidra/DumpMemoryRange.java
tools/ghidra/ExportMemoryRange.java
tools/ghidra/DumpFunctions.java
tools/windows_tracking_geometry.py
tools/regress_heat_frames.py
tools/track_heat_contacts.py
scripts/deploy_phase70.sh
scripts/deploy_phase71.sh
scripts/deploy_phase72.sh
scripts/deploy_phase73_dma.sh
scripts/deploy_phase75_identity.sh
scripts/deploy_phase76_behavior.sh
scripts/deploy_phase77_recovery.sh
scripts/deploy_phase80_host_recovery.sh
scripts/deploy_phase81_ready_quiesce.sh
scripts/deploy_phase82_set70.sh
scripts/deploy_phase91_windows_cadence.sh
scripts/promote_phase91_dma_baseline.sh
scripts/package_dma_baseline.sh
boot/57_sp11_711_phase70_orchestrator
boot/58_sp11_711_phase71_score3
boot/59_sp11_711_phase72_config
boot/60_sp11_713_phase73_dma
boot/62_sp11_713_phase75_identity
boot/63_sp11_713_phase76_behavior
boot/64_sp11_713_phase77_recovery
boot/67_sp11_713_phase80_host_recovery
boot/68_sp11_713_phase81_ready_quiesce
boot/69_sp11_713_phase82_set70
boot/60_sp11_713_dma_baseline
boot/61_sp11_713_dma_previous
tests/test_heat_decoder.py
tests/test_contact_tracker.py
tests/test_windows_classifier.py
tests/test_windows_lifecycle.py
tests/test_windows_tracking_geometry.py
tests/test_kdnet_hidspi.py
tests/test_cfu_payload.py
tests/test_firmware_resources.py
tests/test_source_invariants.py
packaging/initramfs-tools/hooks/sp11-g6ts
```

`spi-geni-qcom.c` is based on the exact Ubuntu Concept controller source and
adds the isolated BIOS-reference transfer helper required by this device.

## Safety and scope

This repository does not contain Microsoft firmware, EFI/driver binaries,
firmware updates, boot images, or initramfs files. It does contain the small
July 17 textual KDNET mode-setup log needed to audit transfer boundaries; the
larger lifecycle logs remain private and are identified only by hashes. The
driver does not flash the touchscreen and contains no CFU or FRU-unlock path.
The GPI-DMA experiments are isolated under `phase54/` and `phase55/`.

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
- Hardware-validated production kernel `7.1.3-sp11-baseline1+` for Phase 91

## License

GPL-2.0. See [LICENSE](LICENSE). Individual files retain their SPDX notices.
