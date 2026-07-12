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

## Single-touch report

The normal response prefix has class 1, copy-length-minus-one value 5 and
content ID `0x40`. The five-byte payload contains flags plus little-endian X
and Y values. Firmware shifts both coordinates right by five. Live corner
captures establish a resulting range of 0 through 1023 on both axes.

Idle reads are invalid host behavior. They provoke class-3 service responses,
which is why direct GPIO gating is mandatory.
