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

The repository root defaults to the isolated Phase 52 FIFO baseline. To build
the hardware-validated Phase 55 DMA/multi-touch matched set instead:

```bash
make phase55 KDIR=/path/to/linux-7.1.1
```

This produces `gpi.ko`, `spi-geni-qcom.ko`, and `g6ts_biosref.ko` under
`phase55/modules/`. These three modules must be built from the same source tree
and used together. The top-level Makefile contains no host-specific paths.

The Phase 55 wrapper checks `include/config/kernel.release` and accepts only
the hardware-validated `7.1.1-sp11-gpicmp1+` target by default. A newer kernel
requires reviewing the GPI and GENI internals and then using
`ALLOW_UNTESTED_KERNEL=1` for the initial porting build. That override is not a
compatibility claim and the result must not replace a known-good boot entry.

Confirm compatibility before loading:

```bash
modinfo -F vermagic spi-geni-qcom.ko
modinfo -F vermagic g6ts_biosref.ko
```

The Phase 65 keyboard-latency boot image must embed both the matched
`spi-geni-qcom.ko` and `g6ts_biosref.ko`. Reusing an older installed
controller module reintroduces successful-transfer `INFO` logging and defeats
the latency test. Assemble it only as a separate initramfs and verify the
embedded module source versions before rebooting.

Run the hardware-independent checks with:

```bash
make test
python3 -m compileall -q tools tests
```

With a locally mounted Windows installation and saved Heat corpus, the full
Phase 68 fidelity regression is:

```bash
python3 tools/regress_heat_frames.py \
  --expect-frames 1381 \
  --classifier-dll /path/to/TouchPenProcessor0C83.dll \
  --base-lifecycle \
  /path/to/etw_3636_frames_20260506
```

The DLL and captures are read-only inputs and are not copied into the tree.

After committing a verified tree and building the matched GCC modules, create
the redistributable source/module artifact with:

```bash
scripts/package_phase68.sh
```

The packager refuses dirty source, missing modules, or a mismatched vermagic.
It includes the complete GPL source snapshot, the three exact-target modules,
build identity, and SHA-256 manifests. It does not include Microsoft files.

The Phase 64 panel profile is checked in as generated configuration. To
reproduce it from a locally supplied Windows component without copying the DLL
into the repository:

```bash
python3 tools/generate_classifier_header.py \
  /path/to/TouchPenProcessor0C83.dll \
  > /tmp/g6ts_classifier_profile.h
cmp /tmp/g6ts_classifier_profile.h \
  phase55/modules/g6ts_classifier_profile.h
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
