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

The Phase 75 device-tree overlay changes only the touchscreen compatible. The
controller retains `qcom,enable-gsi-dma`, `dmas`, and `dma-names`, so transport
selection remains explicit. The isolated initramfs embeds the renamed client
and matched controller/GPI modules and explicitly rejects an embedded legacy
FIFO client.

Phase 73 remains the saved default until Phase 75 passes a hardware boot. The
7.1.3 FIFO baseline and Phase 74 reset reproducer remain separate rollback and
laboratory entries.
