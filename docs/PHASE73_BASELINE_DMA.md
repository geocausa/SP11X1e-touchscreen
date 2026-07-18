# Phase 73 baseline DMA re-home: DMA multi-touch + Phase 72 fix on 7.1.3

Phase 73 brings the full QSPI/GPI-DMA multi-touch stack and the Phase 72
mode-config reset fix onto the 7.1.3 baseline kernel, retiring the 7.1.1
`sp11-gpicmp1+` lab kernel as the working target. This is the furthest the
project has reached: a working DMA multi-touch touchscreen on the baseline
kernel intended as its permanent home.

## What moved

The DMA stack is three custom components: the touch client `g6ts_biosref`, the
custom `spi-geni-qcom` GENI controller (with the biosref QSPI transfer helper),
and the custom `gpi` DMA engine (with the QSPI/GSI changes). All three were
rebuilt from the existing modified sources against the 7.1.3 baseline kernel
headers using the Makefile's `ALLOW_UNTESTED_KERNEL=1` porting path.

Despite ~20-25% upstream drift in the base `spi-geni-qcom.c` and `gpi.c`
between 7.1.1 and 7.1.3, the custom sources compiled clean (exit 0, no
warnings) against 7.1.3 with no source changes: the drift did not intersect the
custom hunks. All three modules carry vermagic `7.1.3-sp11-baseline1+`.

## The device-tree gap (root cause of the first failed boot)

The first 7.1.3 DMA boot loaded and bound all three modules but failed with
`SPI transfer timed out ... stage=1 ret=-110`. Cause: the 7.1.3 baseline DTB
carries the touch node (`qcom,biosref-qspi`, `microsoft,mshw0485-biosref`) but
was authored for FIFO and does NOT declare the GPI-DMA channels. The DMA path
had no channel to run, so the first transfer never completed.

The node names are identical between the FIFO baseline and the DMA lab, which
masked the difference; only the DMA channel wiring distinguishes them. The fix
adds `qcom,enable-gsi-dma`, `dmas`, and `dma-names` to the `spi@a88000` node,
matching the lab DTB (the GPI controller phandle `0x5e` is identical in both).
See [dts/PHASE73_BASELINE_DMA_DTB.patch.md](../dts/PHASE73_BASELINE_DMA_DTB.patch.md).

Follow-up: the shared `qcom,biosref-qspi` property is ambiguous between the FIFO
and DMA personalities. A future cleanup should make the DMA path unambiguous in
the device tree (the `qcom,enable-gsi-dma` gate now present is the natural
discriminator) so this cannot be mis-authored again.

## Validation (on device, 7.1.3-sp11-baseline1+, DMA DTB live)

```
input: Microsoft Surface G6 Touch (DMA) ... spi0.0/input/input1
microsoft-g6ts spi0.0: touch controller initialization scheduled
microsoft-g6ts spi0.0: phase72: GET_FEATURE 0x70 config len=1 bytes=02
microsoft-g6ts spi0.0: phase72: SET_FEATURE 0x70 derived len=2 bytes=01 02
microsoft-g6ts spi0.0: phase72: OUTPUT_REPORT 0x09 len=2 bytes=8e 02
microsoft-g6ts spi0.0: touch controller initialized recoveries=1 resets=0
```

- GSI-DMA confirmed live in the running device tree.
- Touch initialized over GPI-DMA with no stage-1 timeout.
- Phase 72 mode-config fix fired correctly on 7.1.3 as well.
- Zero panel resets at init; touch functional.

## Isolation

Deployed via `scripts/deploy_phase73_dma.sh` to a dedicated `sp11-phase73-dma`
GRUB entry using the baseline kernel + the DMA-patched baseline DTB + an
initramfs embedding the three DMA modules. The stock baseline modules on disk
are restored on script exit, so the default baseline entry stays FIFO/stock; the
Phase 73 entry is self-contained in its own initramfs. The saved GRUB default is
never changed (one-shot `grub-reboot`). Known-good Phase 68 and the safe
baseline remain available for rollback.

## Scope and known gaps

This is a working milestone, not full Windows parity. Many functions and
behaviors captured from the Windows stack (TouchPenProcessor heatmap processing
internals, the full recovery state machine's gating/verification, the richer
cold-boot 0x65 axis config, and other feature exchanges) are not yet ported or
are only partially modeled. Longer soak testing under sustained load on 7.1.3
(matching the ~6h Phase 72 session) remains to be done before promotion to the
default boot entry. Pen support remains out of scope.
