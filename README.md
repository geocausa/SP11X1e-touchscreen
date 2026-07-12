# Surface Pro 11 X Elite touchscreen driver

Experimental Linux support for the `MSHW0485` G6 touchscreen in the OLED
Microsoft Surface Pro 11. The current driver provides working, calibrated
single-touch input on Ubuntu Concept `7.0.0-32-qcom-x1e`.

## Current status

- Power and reset sequencing works.
- Qualcomm GENI protocol 9 transport works in the UEFI-derived FIFO mode.
- The controller completes the class-3/class-7 readiness exchange.
- Active-low GPIO51 gates input reads at the firmware's 5.3 ms interval.
- Normal class-1 touch and release reports work across the full display.
- Coordinates are normalized from 0 through 1023 on both axes.
- Linux identifies the device as a direct touchscreen.
- Live validation completed with no transport, protocol, readiness or GPIO
  errors.

The working driver is intentionally single-touch. The full Windows
multitouch/HEAT path uses a different panel personality and Qualcomm GPI DMA;
it is being developed as an isolated Phase 54 boot path rather than added to
the known-good FIFO driver.

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
tools/analyze_spb_etw_csv.py
```

`spi-geni-qcom.c` is based on the exact Ubuntu Concept controller source and
adds the isolated BIOS-reference transfer helper required by this device.

## Safety and scope

This repository does not contain Microsoft firmware, EFI binaries, firmware
updates, captures, boot images or initramfs files. The driver does not flash
the touchscreen and contains no CFU or FRU-unlock path. The separate GPI-DMA
experiment is documented in
[docs/PHASE54_GPI_DMA.md](docs/PHASE54_GPI_DMA.md).

Use a separate boot entry and retain a known-good kernel. See
[docs/BUILD.md](docs/BUILD.md) and [docs/TESTING.md](docs/TESTING.md).

## Tested hardware

- Microsoft Surface Pro 11 OLED
- Snapdragon X Elite / `x1e80100`
- Touch device `MSHW0485`
- QUP1 SE2 at `0x0a88000`
- Ubuntu Concept kernel `7.0.0-32-qcom-x1e`

## License

GPL-2.0. See [LICENSE](LICENSE). Individual files retain their SPDX notices.
