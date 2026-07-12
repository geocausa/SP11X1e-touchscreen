# Windows HEAT protocol evidence

This document records facts recovered from an existing Windows ETW/KDNET
corpus for the Surface Pro 11 OLED `MSHW0485`. No firmware, Microsoft binary,
ETL file or captured payload is included in this repository.

## Why the UEFI path is single-touch

The Surface-specific UEFI stack exposes report ID `0x40` as a five-byte
absolute-pointer report. Its payload contains a tip flag and one X/Y pair.
That is the known-good report decoded by the current Linux driver.

Windows does not obtain multitouch by adding contacts to report `0x40`.
Instead, it enables the Windows HEAT pipeline and consumes much larger
capacitive heat-map reports. Microsoft's `TouchPenProcessor0C83.dll`, bound to
`HID\\MSHW0485&Col02`, converts those reports into normal OS touch contacts.

## Complete HID report descriptor

A WPA CSV export of the `Microsoft-Windows-SPB-ClassExtension` provider
contains a clean 1,488-byte response:

```text
08 cc 05 00 <1484-byte HID report descriptor>
```

The four-byte response prefix declares the exact remaining descriptor length:
`0x05cc` / 1484 bytes.

For reproducibility, the SHA-256 of the 1,484-byte descriptor (without the
four-byte transport prefix) is:

```text
8534961c82edceecc9e21c612be560b9dd9b3bef7df36233059179c58d47fa57
```

The descriptor has ten top-level collections:

| Collection | Usage page | Usage | Purpose/evidence |
|---|---:|---:|---|
| Col00 | `0xff0b` | `0x000b` | Vendor feature/input reports |
| Col01 | `0x000d` | `0x000f` | Capacitive Heat Map Digitizer |
| Col02 | `0xff0f` | `0x0050` | Vendor HEAT control collection |
| Col03 | `0x000d` | `0x0004` | Touch Screen, report ID `0x40` |
| Col04 | `0xfff4` | `0x0001` | Vendor collection |
| Col05 | `0xff0b` | `0x0101` | Vendor collection |
| Col06 | `0x000d` | `0x0002` | Pen, report ID `0x01` |
| Col07 | `0xffa1` | `0x0060` | Vendor collection |
| Col08 | `0xff0f` | `0x0051` | Vendor HEAT collection |
| Col09 | `0xff0d` | `0x0001` | Vendor collection |

The HEAT digitizer collection advertises report IDs:

```text
05 06 07 08 09 0a 0b 0c 0d 11 12 1a 1c
```

This proves the device descriptor itself contains both the reduced UEFI
touchscreen and the richer Windows HEAT path.

## Active Windows frames

The archived ETW trace contains 1,381 complete report-ID-`0x12` frames:

```text
TX: eb 00 10 04 ff ff ff ff
RX length: 0x0e34 / 3636 bytes
RX prefix: 01 2d 0e 12
```

The descriptor gives report `0x12` a one-byte report ID, a 16-bit scan-time
field and `0x0e2b` bytes of report data. The transport adds its class/length
prefix and alignment, accounting for the observed 3,636-byte read exactly.

One 7,492-byte frame begins with report ID `0x1c`; that size also matches the
descriptor's `0x1d3d`-byte report-data declaration after transport framing.

The large reports contain sparse sensor/heat-map information, not finished
HID contact records. Existing analysis found repeated `0x44`-byte sensor
regions and dominant `0xb4`/`0xb5` fill values. Linux therefore cannot turn
these frames into reliable contacts merely by calling `input_mt_slot()`.

## Observed initialization exchange

The same trace contains a one-time initialization sequence. It retrieves the
device/report descriptors and several feature reports before normal HEAT
frames continue. The distinct outbound writes are recoverable with
`tools/analyze_spb_etw_csv.py`.

Examples with confirmed meanings include:

```text
e2 00 20 00 01 00 00 00        readiness/reset exchange
e2 00 20 00 02 00 00 00        request full HID report descriptor
e2 00 20 00 04 00 00 60        request report 0x60
e2 00 20 00 04 00 00 70        request report 0x70
e2 00 20 00 04 00 00 06        request report 0x06
e2 00 20 00 04 00 00 73        request report 0x73
```

The trace performs the `EB` header/body read immediately after each `E2`
request. GPIO51 is not used as a completion gate for these solicited control
responses; it gates unsolicited input reports.

Other captured writes carry feature-report bodies and must not be replayed
until their direction, length and state requirements are understood. The
analysis tool prints them for offline comparison but never accesses hardware.

## Phase 53 hardware result

Sending function 2 by itself after the known UEFI readiness/reset flow does
not return the report descriptor. A bounded Linux test received a class-3
service response instead, after which the existing readiness recovery restored
normal report-`0x40` touch with no transport, FIFO or protocol errors.

This proves that at least part of the earlier Windows feature/control exchange
is a prerequisite for descriptor access or HEAT mode. Do not replay the
remaining captured writes as an undifferentiated sequence; decode their HID
report types and state requirements first.

## Practical implementation boundary

There are now two distinct development targets:

1. **Transport and mode discovery.** Add an opt-in diagnostic path that can
   retrieve descriptors and record large reports while preserving report
   `0x40` as the default input path.
2. **HEAT processing.** Recover enough sensor geometry and tracking behavior
   to turn raw frames into stable contact IDs, positions and lifetimes. This
   is substantially larger than ordinary HID multitouch parsing.

The next driver change should implement only the first target behind an
explicit experimental option. It must not replace the working UEFI-derived
single-touch path or replay the complete captured Windows sequence.
