# Phase 73 baseline DTB patch: enable GSI-DMA on the touch SPI node

The 7.1.3 baseline device tree carries the touch node (`qcom,biosref-qspi`,
`touchscreen@0` / `microsoft,mshw0485-biosref`) but was authored for the
FIFO personality: it does NOT declare the GPI-DMA channels. The DMA driver
therefore loads and binds, but the first SPI transfer times out
(`SPI transfer timed out ... stage=1 ret=-110`) because no DMA channel is wired.

## Fix

Add three properties to the `spi@a88000` node (the touch controller), matching
the proven 7.1.1 lab DTB. The GPI DMA controller (`dma-controller@a00000`) and
its phandle `0x5e` already exist in the baseline DT unchanged, so the channel
reference is identical to the lab.

Inside `soc@0/geniqup@ac0000/spi@a88000`, immediately after `qcom,biosref-qspi;`:

```
qcom,enable-gsi-dma;
dmas = <0x5e 0x00 0x02 0x04 0x5e 0x01 0x02 0x04>;
dma-names = "tx", "rx";
```

- `0x5e` = phandle of `dma-controller@a00000` (GPI DMA), `#dma-cells = <0x03>`.
- The two channels are TX and RX for the QSPI transport.

## Reproduce

```
dtc -I dtb -O dts <baseline.dtb> > base.dts
# insert the three properties into spi@a88000 after qcom,biosref-qspi;
dtc -I dts -O dtb -o baseline-dma.dtb base.dts
```

Deploy `baseline-dma.dtb` as the Phase 73 entry's device tree. Confirm live with:
`test -e /proc/device-tree/soc@0/geniqup@ac0000/spi@a88000/qcom,enable-gsi-dma`.

## Validated

On 7.1.3-sp11-baseline1+, with the DMA DTB live, the touch controller
initialized over GPI-DMA (no stage-1 timeout), the Phase 72 mode-config fix
fired, and the panel initialized with zero resets.
