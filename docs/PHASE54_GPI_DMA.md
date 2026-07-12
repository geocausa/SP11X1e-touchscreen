# Phase 54: isolated Windows-mode GPI DMA path

Phase 52 remains the known-good boot path. It uses the panel's reduced UEFI
personality, protocol-9 FIFO transfers and report `0x40`. Phase 54 is a
separate experiment for the full Windows HID/HEAT personality.

## Evidence for the split

The Phase 52 Device Tree deliberately removes the `spi10` DMA properties and
sets `qcom,biosref-qspi`. The client then bypasses the normal SPI message path
and calls the UEFI-derived polled FIFO helper.

The Windows ETW trace instead shows normal HID-over-SPI output reports and
large input reports. It retrieves a 1,484-byte report descriptor and receives
3,636-byte report `0x12` and 7,492-byte report `0x1c` frames. The Windows
controller uses Qualcomm GPI DMA.

The ELLX `7.0.0-rc4-10-sl7` tree already contains the necessary protocol-9
GPI building blocks:

- `drivers/dma/qcom/gpi.c`: QSPI TRE generation and native protocol value 9.
- `include/linux/dma/qcom-gpi-dma.h`: QSPI transfer metadata.
- `include/dt-bindings/dma/qcom-gpi.h`: `QCOM_GPI_QSPI` binding value.
- `drivers/spi/spi-geni-qcom.c`: protocol-9 detection, QSPI lane setup and
  forced GPI DMA.
- `drivers/hid/spi-hid/`: HID-over-SPI enumeration and Linux HID integration.

These components must be ported together. Mixing the ELLX SPI controller with
the unmodified Concept GPI DMA engine is not a valid test.

## Exact Denali platform changes

For `spi10` / QUP1 SE2:

1. Enable `gpi_dma1`.
2. Change the controller compatible to `qcom,geni-spi-qspi`.
3. Retain the existing channels but select QSPI protocol:

   ```dts
   dmas = <&gpi_dma1 0 2 QCOM_GPI_QSPI>,
          <&gpi_dma1 1 2 QCOM_GPI_QSPI>;
   dma-names = "tx", "rx";
   ```

4. Keep GPIO49/GPIO50 in the QSPI data-2/data-3 pin state.
5. Bind the child to the HID-over-SPI client rather than `g6ts-biosref`.
6. Preserve GPIO64 power-enable, GPIO48 reset and GPIO51 level-low interrupt.

## On-wire distinction

The Windows/GPI driver uses native QSPI transactions:

- `E2 + 0x002000 + output body` for host writes.
- `EB + address`, followed by the quad receive phase for input header/body.
- Four command bytes and controller-programmed dummy clocks, rather than the
  eight-byte UEFI FIFO templates containing explicit `0xff` placeholders.

This explains why sending function 2 over the UEFI FIFO helper repeatedly
returns a reset response: it tests the reduced personality through the wrong
host path for Windows enumeration.

## Bring-up gates

The first Phase 54 boot must stop after descriptor enumeration. It must not
send captured vendor feature/output reports automatically.

Success gates, in order:

1. GPI TX and RX channels bind to QUP1 SE2 with protocol 9.
2. Hardware reset produces class 3 without DMA errors.
3. Device descriptor request produces class 7.
4. Report descriptor request produces class 8 with exactly 1,484 content
   bytes and SHA-256
   `8534961c82edceecc9e21c612be560b9dd9b3bef7df36233059179c58d47fa57`.
5. The Linux HID parser creates the advertised collections.
6. Large reports are captured and counted without yet turning them into touch
   contacts.

Only after those gates pass should HEAT feature negotiation or contact
processing be added.

## Safety and boot isolation

- Build a new Phase 54 initramfs and GRUB entry.
- Do not overwrite the Phase 52 initramfs, DTB or menu entry.
- Do not make Phase 54 the saved/default entry.
- Keep the Phase 52 modules and hashes as the immediate fallback.
- A failed Phase 54 probe must power/reset the panel to a known state and must
  not flash firmware, unlock FRU, write calibration, or alter storage protect.
