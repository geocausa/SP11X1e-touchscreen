# Surface Pro 11 X Elite touchscreen driver

Experimental Linux support for the `MSHW0485` G6 touchscreen in the OLED
Microsoft Surface Pro 11. The repository preserves two isolated paths: the
working UEFI-derived FIFO/single-touch baseline and the hardware-validated
Phase 55 QSPI/GPI-DMA multi-touch experiment.

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

It is not yet a production or upstream-ready driver. It now includes adaptive
per-frame baseline measurement, conservative broad-contact palm filtering,
jitter smoothing, and one-frame dropout protection. Pressure, merged-contact
separation, measured edge calibration, and broader kernel compatibility remain
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
phase55/
tools/analyze_spb_etw_csv.py
tools/decode_heat_frame.py
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
The Phase 55 client deliberately has no suspend/resume callbacks because
platform suspend is disabled on the tested system after earlier whole-device
crashes.

## Tested hardware

- Microsoft Surface Pro 11 OLED
- Snapdragon X Elite / `x1e80100`
- Touch device `MSHW0485`
- QUP1 SE2 at `0x0a88000`
- Ubuntu Concept kernel `7.0.0-32-qcom-x1e`
- Experimental kernel `7.1.1-sp11-gpicmp1+` for Phase 55

## License

GPL-2.0. See [LICENSE](LICENSE). Individual files retain their SPDX notices.
