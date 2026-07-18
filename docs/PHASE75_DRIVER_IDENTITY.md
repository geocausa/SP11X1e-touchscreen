# Phase 75: unambiguous production driver identity

Phase 73 proved the DMA multi-touch stack on the 7.1.3 baseline, but the DMA
client and the legacy UEFI/FIFO client both built as `g6ts_biosref.ko`, used
the same `microsoft-g6ts` driver name, and matched the same
`microsoft,mshw0485-biosref` compatible. Because Phase 73 embeds DMA in its
initramfs while restoring FIFO on the root filesystem, even `modinfo
g6ts_biosref` described a different driver from the one actually running.

Phase 75 removes that ambiguity without changing the touch algorithm or DMA
protocol:

| Identity | Production DMA | Legacy FIFO |
| --- | --- | --- |
| Source | `mshw0485_touch.c` | `src/g6ts_biosref.c` |
| Module | `mshw0485_touch.ko` | `g6ts_biosref.ko` |
| Driver name | `mshw0485-touch` | `microsoft-g6ts` |
| DT compatible | `microsoft,mshw0485` | `microsoft,mshw0485-biosref` |
| Parameter prefix | `mshw0485_touch.*` | `g6ts_biosref.*` |

The Phase 75 device-tree overlay converts the retained 7.1.3 FIFO baseline
into the complete production personality: it adds `qcom,enable-gsi-dma`,
`dmas`, and `dma-names` to the controller and changes the touchscreen
compatible. A fresh clone therefore needs no ignored or prebuilt DMA DTB. The
isolated initramfs embeds the renamed client and matched controller/GPI modules
and explicitly rejects an embedded legacy FIFO client.

## Hardware validation

Phase 75 booted successfully on the Surface Pro 11 OLED on 2026-07-18:

```text
kernel:             7.1.3-sp11-baseline1+
client:             mshw0485_touch BDFAAF7F53AA06F00CA30FA
controller:         spi_geni_qcom 393A6B36EC5A67BDDC47040
DMA engine:         gpi 24B1195ED15A417793F5F0E
DT compatible:      microsoft,mshw0485
legacy FIFO loaded: no
panel resets:       0
transport errors:   0
```

The panel completed the Phase 72 mode-config exchange, registered as
`Microsoft Surface G6 Touch`, and the user confirmed quick taps, dragging,
two-finger pinch and fast on-screen typing behaved normally. Phase 75 is now
the saved default. Phase 73 and the 7.1.3 FIFO baseline remain distinct
fallbacks; Phase 74 remains an explicitly labelled reset reproducer.
