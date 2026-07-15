# Building

## Supported baseline

The current source targets Ubuntu Concept kernel:

```text
7.0.0-32-qcom-x1e
Ubuntu source package linux-qcom-x1e 7.0.0-32.32
```

The controller source reaches into the exact `spi-geni-qcom` implementation,
so treat other kernel versions as ports requiring review rather than as
drop-in compatible builds.

## External module build

With the matching kernel and headers installed:

```bash
make -C /lib/modules/$(uname -r)/build M="$PWD" modules
```

This produces:

```text
spi-geni-qcom.ko
g6ts_biosref.ko
```

Confirm compatibility before loading:

```bash
modinfo -F vermagic spi-geni-qcom.ko
modinfo -F vermagic g6ts_biosref.ko
```

## Device tree

The Denali source enables QUP1 SE2, removes DMA properties for the isolated
firmware-style path and adds:

```dts
interrupts = <51 IRQ_TYPE_LEVEL_LOW>;
interrupt-gpios = <&tlmm 51 GPIO_ACTIVE_LOW>;
power-gpios = <&tlmm 64 GPIO_ACTIVE_HIGH>;
reset-gpios = <&tlmm 48 GPIO_ACTIVE_HIGH>;
```

Build the OLED DTB through the matching Ubuntu kernel tree. Do not replace the
normal boot image. Embed the modified DTB in a separate stubble image and use
a separate initramfs containing the matching modules.

## Secure Boot

Locally produced modules and stubble images are unsigned. This repository does
not automate key enrollment or disable Secure Boot.
