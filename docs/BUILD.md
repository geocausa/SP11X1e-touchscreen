# Building

## Supported baseline

The Phase 91 production DMA source targets the Ubuntu Concept baseline kernel:

```text
7.1.3-sp11-baseline1+
```

The controller source reaches into the exact `spi-geni-qcom` implementation,
so treat other kernel versions as ports requiring review rather than as
drop-in compatible builds.

A separate installer supports an intentionally clean upstream 7.1.3 build by
compiling the complete GPI/GENI/client set against the recipient machine's
exact headers and symbol versions. It does not make the prebuilt
`7.1.3-sp11-baseline1+` modules portable. See
[PORTABLE_UPSTREAM_713.md](PORTABLE_UPSTREAM_713.md).

## Production DMA build

With the matching kernel and headers installed:

```bash
make KDIR=/lib/modules/7.1.3-sp11-baseline1+/build
```

This builds the matched production set under `phase55/modules/`:

```text
gpi.ko
spi-geni-qcom.ko
mshw0485_touch.ko
```

The equivalent explicit target is:

```bash
make phase55 KDIR=/path/to/linux-7.1.3
```

These three modules must be built from the same source tree and used together.
The top-level Makefile contains no host-specific paths.

The historical FIFO client remains available explicitly:

```bash
make legacy-fifo KDIR=/lib/modules/7.1.3-sp11-baseline1+/build
```

It produces `g6ts_biosref.ko` and must not be mixed with the production DMA
client or loaded from the same initramfs.

The DMA wrapper checks `include/config/kernel.release` and accepts only the
hardware-validated `7.1.3-sp11-baseline1+` target by default. A newer kernel
requires reviewing the GPI and GENI internals and then using
`ALLOW_UNTESTED_KERNEL=1` for the initial porting build. That override is not a
compatibility claim and the result must not replace a known-good boot entry.

Confirm compatibility before loading:

```bash
modinfo -F vermagic spi-geni-qcom.ko
modinfo -F vermagic mshw0485_touch.ko
```

The production DMA boot image must embed the matched `gpi.ko`,
`spi-geni-qcom.ko`, and `mshw0485_touch.ko`. Assemble it only as a separate
initramfs and verify all embedded module source versions before rebooting.

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
the Phase 91 redistributable source/module artifact with:

```bash
scripts/package_dma_baseline.sh
```

The packager refuses dirty source, missing modules, or a mismatched vermagic.
It includes the complete GPL source snapshot, the three exact-target modules,
build identity, and SHA-256 manifests. It does not include Microsoft files.
`scripts/package_phase68.sh` is retained only to reproduce the historical
7.1.1 Phase 68 artifact.

To create the source-only clean-upstream 7.1.3 installer bundle instead:

```bash
scripts/package_upstream_713_phase91.sh
```

That archive deliberately contains no `.ko` files. Its top-level `install.sh`
builds on the target, checks the exact vermagic against the stock kernel,
derives the Phase 91 DTB from the installed pristine Denali OLED DTB, and adds
only an isolated one-shot GRUB entry.

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

The retained Denali FIFO baseline enables QUP1 SE2 and removes its DMA
properties. Phase 75 derives the production tree from that baseline using
`dts/phase75-mshw0485-production.dtso`, which adds the GPI-DMA channels and
changes the client compatible to `microsoft,mshw0485`. No prebuilt or ignored
DMA DTB is required.

The common touchscreen node provides:

```dts
interrupts = <51 IRQ_TYPE_LEVEL_LOW>;
interrupt-gpios = <&tlmm 51 GPIO_ACTIVE_LOW>;
power-gpios = <&tlmm 64 GPIO_ACTIVE_HIGH>;
reset-gpios = <&tlmm 48 GPIO_ACTIVE_HIGH>;
```

For a fresh machine, use the Phase 75 deployment script to derive and verify
the DMA DTB and first rescue initramfs. After validating it, deploy Phase 91:

```bash
sudo ./scripts/deploy_phase75_identity.sh
# reboot once into Phase 75, then return here
sudo ./scripts/deploy_phase91_windows_cadence.sh
```

After Phase 91 boots, reaches Heat, and retains zero fault counters, promote it
and reduce the active GRUB menu to the production DMA image plus two fallbacks:

```bash
sudo ./scripts/promote_phase91_dma_baseline.sh
```

The promotion script validates the live hardware counters, archives every old
SP11 menu script, preserves all `/boot` experiment assets, installs a previous
DMA and FIFO rescue entry, and changes the saved default only after the new
GRUB configuration passes validation. See
[BASELINE_DMA_PHASE91.md](BASELINE_DMA_PHASE91.md).

## Secure Boot

Locally produced modules and stubble images are unsigned. This repository does
not automate key enrollment or disable Secure Boot.
