# Phase 68 proven recovery boundary

Phase 68 corrects the cold-start regression introduced in Phase 66 and only
partially corrected in Phase 67. It deliberately separates three evidence
classes: HID-SPI transport, panel mode entry, and Windows collection or touch
processing setup.

## Hardware result that defines the regression

All trials used the same Surface Pro 11 OLED, hybrid DTB, 7.1.1 kernel, and
QSPI/GPI-DMA transport.

- Phase 65 cold-booted and delivered working multitouch.
- Phase 66 replayed the extended Windows sequence and timed out at its second
  report-09 exchange.
- Phase 67 removed that unsupported exchange, successfully completed and
  validated GetFeature `0x73`, then timed out waiting for its first Heat
  frame at stage 13.
- Rebooting the unchanged Phase 65 initramfs immediately restored touch and
  produced active GPIO51 interrupts.

This A/B result isolates the failure to the extended initialization sequence;
the kernel, DTB, GPI DMA engine, GENI controller, IRQ and panel remain good.

## Windows evidence boundary

The complete ETW capture genuinely contains report `0x60`, four report-`0x65`
exchanges, report `0x06`, report-`0x09` A1/A5 payloads, SetFeature `0x05`, and
GetFeature `0x73` before Heat streaming. Those observations remain valid, but
the capture observes the whole Windows HID collection stack, not a single
driver recovery function.

The current `TouchPenProcessor0C83.dll` was inspected in Ghidra. Its exported
`InitializeHeatProcessor` constructs and initializes processing state. The
DLL imports HID descriptor parsing (`HidP_GetCaps` and `HidP_GetValueCaps`),
but imports no device-open, DeviceIoControl, HID write, or feature-report
transport API. The kernel `hidspi.sys` and `HidSpiCx.sys` components implement
generic report transport. Therefore the ETW ordering cannot be copied whole
into the Linux panel reset path without also reproducing the missing Windows
collection state and asynchronous ownership.

## Phase 68 recovery sequence

After a full ACPI/GPIO power cycle, the kernel performs only the sequence
already proven in Phase 55 through Phase 65:

1. Wait for and validate the reset response.
2. Read and validate the HID-SPI device descriptor.
3. Read the exact-length HID report descriptor.
4. SetFeature `0x05` with the mode-enable byte.
5. GetFeature `0x70` and validate its response.
6. SetFeature `0x70` with the mode-enable byte.
7. SetFeature `0x56` with the established seven-byte mode handshake.

Reports `0x60`, `0x65`, `0x06`, `0x09`, and `0x73` are not emitted by cold
start or class-3 recovery. A source-invariant test prevents their accidental
reintroduction.

## Retained Phase 67 fixes

Phase 68 keeps the changes independent of the failed replay:

- every contact-slot output is initialized before the no-active-track return;
- both DMA channel configurations and submission cookies are checked;
- partial DMA setup terminates both channels and restores ownership/masks;
- message status survives every early transport failure;
- ACPI reset, power-off and suspend errors are propagated;
- classifier, candidate extraction, assignment and smoothing are unchanged.

## Validation status

Pre-deployment validation completed successfully:

```text
unit/source-invariant tests: 36/36
Windows Heat corpus:         1381/1381 decoded, 0 errors
contacts classified:         class0=1106 class2=6 class3=1
fixed/float class mismatch:  0
GCC 15 W=1 build:            passed
Clang 21 W=1 build:          passed (clean exact-source output)
sparse C=2 endian audit:     passed
client cppcheck findings:    0
client strict checkpatch:    0 errors, 0 warnings, 0 checks
packager shellcheck:         passed
```

The final GCC module source versions are:

```text
gpi:             24B1195ED15A417793F5F0E
spi_geni_qcom:   393A6B36EC5A67BDDC47040
g6ts_biosref:    E7A094AA381F6556CE14985
```

The dedicated Phase 68 entry subsequently cold-booted on the target Surface
with kernel `7.1.1-sp11-gpicmp1+`. The running modules matched all three source
versions above, the client registered `Microsoft Surface G6 Touch (DMA)`, and
initialization completed at 2.686 seconds with:

```text
microsoft-g6ts spi0.0: touch controller initialized recoveries=1 resets=0
```

Interactive touch worked after boot and GPIO51 accumulated 1,320 interrupts
during the initial check. This validates the restored startup/recovery boundary
on hardware. Phase 68 remains experimental until longer multitouch, fast
two-handed keyboard, repeated class-3 recovery, and suspend/resume testing are
complete.
