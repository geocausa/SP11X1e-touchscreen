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
- Bounded recovery after the panel emits a class-3 reset.
- High-volume GPI tracing disabled by default.

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

## Contents

- `modules/gpi.c`: matched QSPI/GPI DMA engine.
- `modules/spi-geni-qcom.c`: matched GENI QSPI controller.
- `modules/g6ts_biosref.c`: HID-over-SPI client and heatmap contact tracker.
- `dts/x1-microsoft-denali.dtsi`: exact tested Surface device-tree source.
- `../tools/decode_heat_frame.py`: offline report-`0x12` decoder.

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

The tested source is based on internal DMA-engine and GENI structures. A later
kernel such as 7.2 requires a source-level rebase and hardware validation; a
matching version string alone is not sufficient.

## Safety boundary

This code does not flash firmware, unlock calibration storage, or execute the
UEFI/PRE-OS FIFO transport. Keep a separate known-good kernel/GRUB entry.

## Known limitations

- Contact extraction is a simple connected-component tracker, not Microsoft's
  complete `TouchPenProcessor0C83.dll` algorithm.
- Palm rejection, pen extraction, pressure, contact shape, and merged-finger
  separation are not implemented.
- Threshold and axis calibration are currently fixed for the tested OLED
  panel.
- Suspend/resume code is implemented but has not completed a long-duration
  soak test.
- The source still exposes laboratory diagnostics and is not ready for
  upstream review.
