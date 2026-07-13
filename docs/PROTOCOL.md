# Recovered protocol summary

The implementation is derived from static analysis of the Surface UEFI touch
drivers and confirmed against live responses from `MSHW0485`.

## Transport

- Qualcomm GENI protocol 9 is already resident.
- 40 MHz clock.
- FIFO programmed I/O with the normal DMA path isolated.
- Combined asymmetric transmit/receive commands.
- UEFI mode-1 EB framing for header and body reads.

Header command:

```text
EB 00 10 00 FF FF FF FF
```

Body command:

```text
EB 00 10 04 FF FF FF FF
```

Descriptor/readiness command:

```text
E2 00 20 00 01 00 00 00
```

## Startup

1. Establish reset, power and GPIO51 input state.
2. Power the panel and deassert reset using the recovered delays.
3. Send the E2 readiness command.
4. Class 3 is a continuation case and causes another readiness command.
5. Class 7 completes readiness.
6. Repeat the readiness path after the controller reset used by the Surface
   HID driver.
7. Poll active-low GPIO51 every 5.3 ms and read only while input is pending.

The observed class-7 body is 28 bytes. It is retained in full by the driver's
diagnostic state attribute.

## Readiness descriptor

The class-7 payload is the Microsoft HID-over-SPI device descriptor. Observed
body, prefix included:

```text
07 18 00 00 18 00 00 03 cc 05 00 20 00 02 00 20 5e 04 83 0c 04 00 01 00 00 00 00 00
```

After the three-byte prefix (class 7, length 0x0018) and one alignment byte,
the little-endian fields line up with the HID-over-SPI device descriptor
layout, anchored by the Microsoft vendor ID:

| Field             | Value  | Meaning                     |
| ----------------- | ------ | --------------------------- |
| wDeviceDescLength | 0x0018 | 24 bytes                    |
| bcdVersion        | 0x0300 | descriptor version 3.0      |
| wReportDescLength | 0x05cc | 1484-byte report descriptor |
| wMaxInputLength   | 0x2000 | tentative                   |
| wMaxOutputLength  | 0x0200 | tentative                   |
| wMaxFragmentLength| 0x2000 | tentative                   |
| wVendorID         | 0x045e | Microsoft                   |
| wProductID        | 0x0c83 | G6 touch controller         |
| wVersionID        | 0x0004 |                             |
| wFlags            | 0x0001 |                             |
| dwReserved        | 0      |                             |

The three length fields marked tentative depend on where the alignment byte
sits; the vendor/product anchor is unambiguous. The report descriptor itself
(1484 bytes, presumably behind a further read command) has not been retrieved
yet and is the natural entry point for multitouch work.

EFI provenance of the readiness flow: helper RVA `0x5B88` sends the E2
command and accepts class 7 (the phase-3 static analysis flags it as
mandatory before input polling), RVA `0x5964` acknowledges class-3 service
responses by re-running that helper, and RVA `0x6398`
(`ResetHidSpiDeviceController`) performs the reset-then-readiness pass the
Surface HID driver executes before starting its polling loop.

## Single-touch report

The normal response prefix has class 1, copy-length-minus-one value 5 and
content ID `0x40`. The five-byte payload contains flags plus little-endian X
and Y values. Firmware shifts both coordinates right by five. Live corner
captures establish a resulting range of 0 through 1023 on both axes.

Idle reads are invalid host behavior. They provoke class-3 service responses,
which is why direct GPIO gating is mandatory.
