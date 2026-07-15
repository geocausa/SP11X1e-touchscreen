# Phase 55 DMA multi-touch milestone

Phase 55 is the first hardware-validated Linux implementation of the Surface
G6 panel's raw-heatmap personality. It is intentionally isolated from the
known-good Phase 52 FIFO/single-touch path.

## What works

- Qualcomm GENI protocol-9 QSPI over GPI DMA.
- HID-over-SPI reset, device-descriptor, and 1,484-byte report-descriptor
  exchanges.
- Automatic cold startup with no sysfs writes.
- Report `0x12` Heat container decoding.
- A 68-column by 46-row sensor grid extracted from section `0x0100`.
- Up to ten Linux type-B multi-touch slots.
- Two-finger pinch and zoom on real hardware.
- Three-finger desktop window gestures on real hardware.
- Windows-derived fixed-threshold candidate extraction, conservative palm
  filtering, firmware NSR-bin gating, predicted global tracking, coordinate
  smoothing, and bounded dropout protection.
- Bounded recovery after the panel emits a class-3 reset.
- High-volume GPI tracing disabled by default.
- Known duplicate QSPI completion notices handled quietly rather than flooding
  the kernel log.
- Successful QSPI transactions use disabled-by-default dynamic debug rather
  than rate-limited informational logging.
- Manual DMA laboratory controls are hidden by default. They require the
  explicit boot/module option `g6ts_biosref.lab_controls=1`.
- A malformed Heat frame releases Linux contacts instead of leaving a stale
  touch active.

## Hardware validation

Validation was performed on a Surface Pro 11 OLED (`MSHW0485`) with the
experimental kernel `7.1.1-sp11-gpicmp1+`.

- 6,458 heatmap frames were processed in one session.
- 5,431 frames contained one or more detected contacts.
- 1,027 frames were idle.
- Zero heatmap decode errors occurred.
- A deliberate full recovery completed on its first attempt with no transport
  error.
- Two simultaneous fingers, pinch, and zoom were confirmed in the desktop.
- A separate polished-build run processed 2,791 Heat frames: 2,485 contact
  frames and 306 idle frames, with zero decode or recovery errors. One-, two-,
  and three-finger gestures were confirmed and all contacts released cleanly.
- All 1,381 saved Windows Heat frames passed offline regression without a
  known-good fingertip being rejected by the palm boundary.
- All frames supplied a valid 16-bin NSR metadata record. Its maximum value was
  2 against Windows' strict cutoff of 655, producing zero NSR rejections and no
  change to the established corpus contacts.

## Contents

- `modules/gpi.c`: matched QSPI/GPI DMA engine.
- `modules/spi-geni-qcom.c`: matched GENI QSPI controller.
- `modules/g6ts_biosref.c`: HID-over-SPI client and heatmap contact tracker.
- `dts/x1-microsoft-denali.dtsi`: exact tested Surface device-tree source.
- `../tools/decode_heat_frame.py`: offline report-`0x12` decoder.
- `../docs/PHASE59_NSR_METADATA.md`: exact section-`0xff00` type-`0x04` format,
  Windows call path, row mapping, cutoff, and corpus evidence.

The three modules are a matched set. Do not combine a Phase 55 module with a
stock or Phase 54 controller/DMA module.

## Build

Build only against the exact target kernel tree and configuration:

```bash
cd phase55/modules
make clean
make -j"$(nproc)" KDIR=/path/to/linux-7.1.1
modinfo gpi.ko spi-geni-qcom.ko g6ts_biosref.ko | grep vermagic
```

The wrapper refuses a kernel release other than the exact validated
`7.1.1-sp11-gpicmp1+`. `ALLOW_UNTESTED_KERNEL=1` exists only for deliberate
source-rebase work; it does not make a mismatched module safe to load.

The tested source is based on internal DMA-engine and GENI structures. A later
kernel such as 7.2 requires a source-level rebase and hardware validation; a
matching version string alone is not sufficient.

## Safety boundary

This code does not flash firmware, unlock calibration storage, or execute the
UEFI/PRE-OS FIFO transport. Keep a separate known-good kernel/GRUB entry.

## Known limitations

- Candidate extraction and the core predicted assignment structure are ported
  from `TouchPenProcessor0C83.dll`. The later four-score shape classifier's
  architecture and tables are located, but its class labels and temporal
  transitions are not yet proven well enough to filter live contacts.
- Pen support is deliberately out of scope; the driver is finger-only.
- Pressure, contact shape, and merged-finger separation are not implemented.
- Heat-byte calibration remains identity and edge calibration remains at the
  validated 0..32767 mapping until repeatable labelled measurements are
  available.
- Suspend/resume callbacks are deliberately absent while platform suspend is
  disabled because of prior whole-device crashes.
- The unsafe captured Windows output-replay hook has been removed. Manual
  laboratory diagnostics remain compiled for reproducibility but are
  inaccessible unless explicitly enabled at module load. The architecture is
  still not upstream-ready.
