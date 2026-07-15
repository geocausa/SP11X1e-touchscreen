# Phase 66 Windows-aligned panel recovery

> **Superseded after hardware failure.** The Phase 66 boot timed out at stage
> 12 because this revision mixed a second report-09 pair from a partial KD
> recovery capture into the complete ETW cold-start path. Do not deploy it.
> Phase 67 records the corrected evidence boundary and implementation.

Phase 66 addresses the skipped characters and visible pauses that remained
after the Phase 65 latency experiment. The input classifier and compositor
were not the source of the long stalls. A paired trace showed:

- balanced type-B touch down/up events;
- classifier execution below 0.24 ms at the maximum;
- GNOME Shell off-CPU intervals below 52 ms;
- repeated `touch controller initialized` messages at 1172.180, 1186.622,
  1227.995, 1234.264, and 1240.509 seconds.

Each class-3 panel notification disabled input, released every contact, and
started a full panel power cycle. Those repeated recoveries account for the
visible keyboard freezes and omitted characters.

## Recovered Windows transaction order

The complete Windows SPB ETW trace contains the following volatile HID
initialization after device and report descriptor enumeration:

1. GetFeature `0x60`.
2. Four OutputReport `0x65` exchanges.
3. GetFeature and SetFeature `0x70`.
4. SetFeature `0x56`.
5. GetFeature `0x06`.
6. OutputReport `0x09` A1 and A5.
7. SetFeature `0x05`.
8. GetFeature `0x73`.
9. Heat report `0x12` streaming.

A later KD capture on the same machine also records a second A1/A5 pair after
SetFeature `0x05`. It reveals an important versioning detail: the report-09
profile bytes changed from `1a 03` in the May ETW trace to `14 03` in the June
KD trace. The response to feature `0x73` carries those same two profile bytes.
The discarded laboratory replay hard-coded the older value and made unsafe
assumptions about overlapping replies; it is not reused.

## Driver changes

- Reproduce the Windows report-0x60 and report-0x65 collection setup.
- Put reports `0x70`, `0x56`, `0x06`, `0x09`, and `0x05` in Windows order.
- Start with the current `0314` profile, verify it through report `0x73`, and
  retain the reported value for subsequent recovery attempts.
- Send the later Windows A1/A5 pair only with the verified profile.
- Treat every exchange as bounded and validate its response class, report ID,
  and minimum payload length.
- Do not declare initialization successful until a complete report-`0x12`
  Heat frame has arrived.
- Count and log reset notifications, successful recoveries, failed recoveries,
  failure stage, and time between resets.
- Restore the three-frame normal contact confirmation used by Phase 64. The
  Phase 65 two-frame experiment did not fix the pauses and unnecessarily
  reduced the transient-noise margin.

All added panel commands are volatile HID feature/output reports observed in
normal Windows operation. The driver has no firmware-update, CFU, calibration
write, FRU-unlock, or persistent-storage path.

## Offline validation

- 33 deterministic decoder, classifier, and tracker tests pass.
- The matched three-module set builds against `7.1.1-sp11-gpicmp1+` with
  `W=1` and no compiler warnings.
- `g6ts_biosref.c` passes strict checkpatch with no errors, warnings, or
  checks.
- Hardware reset-soak and fast two-hand keyboard validation remain required
  before publication.

## Isolated deployment checkpoint

Phase 66 is installed as one-shot GRUB entry `sp11-phase66` with command-line
marker `sp11_entry=7.1.1-phase66`. Its initramfs contains the new client, the
quiet Phase 65 controller, and the previously validated GPI module:

```text
client source version:     DEE36E639679D0EC7C283E7
controller source version: 3FAD9771148895A06E6A06E
GPI source version:        FC303CACFF2F7773477482D

b3bc79c67379443cdc05531945c9aeae95e80ffbed87a988d1d708490dbed13c  initrd.img-7.1.1-sp11-gpicmp1+-phase66
fcefdc928b6e45a8212722c9132b9da2dc1c197fc4890f7a9bab3c31d1584b94  sp11-7.1.1-phase66-hybrid.dtb
6f263da75052c54b16d9be21b315beab6b45a2c27c08710d5362b033b4aebf30  vmlinuz-7.1.1-sp11-gpicmp1+
```

The root-filesystem modules were restored after initramfs assembly. The saved
GRUB default remains the 7.1.3 baseline; only `next_entry` selects Phase 66.
