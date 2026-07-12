# Phase 54 GPI-DMA HID/HEAT experiment

This directory is intentionally separate from the working Phase 52 FIFO
driver. It contains the complete out-of-tree module source needed to test the
panel's Windows-style protocol-9 QSPI/GPI-DMA personality on Ubuntu Concept
`7.0.0-32-qcom-x1e`.

## Components

- `modules/gpi.c`: Qualcomm GPI DMA with QSPI TRE support.
- `modules/spi-geni-qcom.c`: GENI protocol-9 QSPI/GPI controller.
- `modules/spi-hid-core.c`: HID-over-SPI enumeration and Linux HID bridge.
- `dts/x1-microsoft-denali.dtsi`: Denali DT with GPI DMA1, QSPI channels,
  GPIO64 power, GPIO48 reset and GPIO51 interrupt.

The QSPI controller and GPI DMA changes originate from the ELLX
`7.0.0-rc4-10-sl7` tree and are compiled here against the exact Concept kernel
ABI. The HID client has been adapted from pinctrl-only power sequencing to the
Surface Pro GPIO wiring.

## Build the modules

```bash
cd phase54/modules
make clean
make -j"$(nproc)"
```

Expected outputs:

```text
gpi.ko
spi-geni-qcom.ko
spi_hid.ko
```

All three must report the target kernel in `modinfo ... | grep vermagic`.
They are a matched set; do not combine only one or two with the stock stack.

## Build the DTB

Use a disposable copy of the matching Concept kernel source:

```bash
cp phase54/dts/x1-microsoft-denali.dtsi \
  "$KSRC/arch/arm64/boot/dts/qcom/x1-microsoft-denali.dtsi"
cp phase54/modules/include/dt-bindings/dma/qcom-gpi.h \
  "$KSRC/include/dt-bindings/dma/qcom-gpi.h"
make -C "$KSRC" -j"$(nproc)" dtbs
```

The required result is
`arch/arm64/boot/dts/qcom/x1e80100-microsoft-denali-oled.dtb`.
Decompilation must show:

```text
dma-controller@a00000 status = "okay"
spi@a88000 compatible = "qcom,geni-spi-qspi"
dmas protocol cells = 4 / QCOM_GPI_QSPI
touchscreen@0 compatible = "hid-over-spi"
```

## First boot boundary

The initial test is descriptor enumeration only. Do not automatically replay
captured vendor feature/output reports. Success means class 3 reset, class 7
device descriptor, and class 8 report descriptor with 1,484 content bytes and
SHA-256:

```text
8534961c82edceecc9e21c612be560b9dd9b3bef7df36233059179c58d47fa57
```

Keep Phase 52 as the default. Phase 54 must use a dedicated initramfs and EFI
kernel image containing the Phase 54 DTB. The menu template is
`boot/45_sp11_touch_phase54`; its filesystem UUID and paths are machine
specific and must be reviewed before installation.

## Current SP11 build

On the development Surface, all three modules linked against
`7.0.0-32-qcom-x1e`, the DTB compiled, and the dedicated boot artifacts have
these hashes:

```text
7179266be85f31ede3cd91ed7947ae9c8fc5145df43e6cdbfac929411d6a12d2  initrd.img-7.0.0-32-qcom-x1e-phase54
adbaf627c4d8d0d92fa74f667112ccd175563ebcac2a902babfa6138a1d8630b  vmlinuz-7.0.0-32-qcom-x1e-sp11-phase54-gpi-heat
30b42dd2e7720962a931cd8590a4b06994cda52c42db989d18cea66b2a2b621e  x1e80100-microsoft-denali-oled.dtb
```

Hardware enumeration has not yet been tested at the time of this commit.
