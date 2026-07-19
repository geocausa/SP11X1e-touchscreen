# Windows report-`0x09` feedback producer

This note records the static producer trace completed against the matching
ARM64 `TouchPenProcessor0C83.dll`. It closes the Windows half of the dynamic
report-`0x09` question raised by the July 2026 KDNET capture. It does not claim
that the panel-side consumer is fully decoded.

```text
file:   TouchPenProcessor0C83.dll
size:   9,504,272 bytes
md5:    8a87a1e4983d2446e495e39c6ab4f031
sha256: 615a28136f14678298dcd9f009c9295456a9e7ce878717b58d371d343b4c7132
```

The binary is not redistributed. Function addresses below use its preferred
image base and are retained so the analysis can be reproduced in Ghidra.

## Transport envelope

`FUN_1800615e8` is the common feedback sender:

- it rejects logical payloads longer than 63 bytes;
- it copies exactly the requested bytes into a zero-padded internal report
  buffer;
- it resolves HID Usage Page `0xff00`, Usage `0xc9`, as an Output report via
  `FUN_180060ac8`;
- it submits the resulting HID report through the device-interface vtable at
  offset `0x10`, with the caller-selected retry count.

The live descriptor maps that usage to Output Report `0x09`, with 63 content
bytes. The 72-byte HID-SPI transfer observed over KDNET is therefore the
rounded transport representation of this output report, not a literal array
embedded in the DLL.

## Feedback families

The second content byte selects a feedback schema. The binary constructs at
least these report-`0x09` families:

| Content prefix | Producer | Recovered role |
|---|---|---|
| `8e a0` | `FUN_180062270` | feedback subtype A0 |
| `8e a1` | `FUN_180061278` | display-state feedback |
| `8e a2` | `FUN_180061ab0` | FeedbackManager V03 |
| `8e a3` | `FUN_1800610e8` | feedback subtype A3 |
| `8e a4` | `FUN_180062458` | feedback subtype A4 |
| `8e a5` | `FUN_180061ec8` | FeedbackManager V06 |
| `8e a8` | `FUN_180062948` | feedback subtype A8 |

This proves that `0x09` is a general host-to-firmware feedback envelope. Its
captured A/B/C variants are not three fixed touchscreen mode commands.

## Display-state feedback (`8e a1`)

`FUN_180062af0` fills the pending display-state structure used by
`FUN_180061278`. The ETW metadata names its fields:

```text
displayState
stitchingFlag
hingeAngle
IsZfiDataValid
LastAveragePenVoltage
LastAverageZDistanceWithPressure
IsTouchpadPayloadValid
TouchpadPayload.State
RectAnt.ShortAntsStart / End
RectAnt.LongAntsStart / End
```

The directly proven leading layout is:

| Content offset | Width | Source |
|---:|---:|---|
| 0 | 1 | constant `0x8e` |
| 1 | 1 | constant `0xa1` |
| 2 | 1 | display state |
| 3 | 1 | stitching flag |
| 4 | 4 | hinge angle |
| 8..35 | 28 | optional ZFI, pen-voltage/distance and touchpad state |
| 40 | 2 | persistent FastHostId |

`FUN_180062bb8` writes FastHostId at object offset `0x89`, which is content
offset 40 in the `a1` buffer. Its callers initialize that value from persistent
storage and generate a 10-bit fallback if the read fails. In the capture both
hinge angle and FastHostId happened to be `0x0190`; they are independently
owned values, not duplicated constants.

The captured A0/A1 distinction at content offset 2 is therefore display state,
not a packet sequence number.

## FeedbackManager V06 (`8e a5`)

`FUN_180060e30` initializes the V06 buffer with `8e a5` and sequence byte zero.
`FUN_180061ec8` sends all 63 bytes and updates the following fields:

| Content offset | Width | Proven behavior |
|---:|---:|---|
| 0..1 | 2 | constant `8e a5` |
| 2 | 1 | successful-send sequence byte; incremented after success |
| 3 | 1 | current-feedback flags; bit 1 is set, bit 0 denotes pending display state |
| 4..7 | 4 | pending display-state summary when present |
| 39..40 | 2 | current persistent FastHostId |
| 46..47 | 2 | V06 validity/attribute flags; sender always adds bit `0x0040` |

`FUN_180062ca8` is the rich V06 record builder. Its ETW record is named
`FeedbackManager_UpdatePenData`. It copies the current feedback-manager record
into content offsets 8..38, then copies provider/display-alignment fields into
content offsets 41..55:

| Object write | Content | Source |
|---|---:|---|
| `+0x1a9 .. +0x1c7` | 8..38 | current pen/feedback record |
| `+0x1c8` | 39..40 | FastHostId |
| `+0x1ca .. +0x1ce` | 41..45 | provider record bytes 2..6 |
| `+0x1cf` | 46..47 | computed validity/attribute bitmap |
| `+0x1d1 .. +0x1d8` | 48..55 | provider record bytes 9..16 |

An exhaustive decompiler scan of 2,464 functions for these object offsets
confirms that `FUN_180062ca8` is the only function containing the complete
write set. The initializer and V03/V06 senders touch only the expected flag,
host-ID, and sequence fields.

The V06 bitmap starts with `0x4252` and conditionally adds bits for record
presence and provider state. A captured `52 43` at content offsets 46..47 is
the little-endian value `0x4352`: the base bitmap plus the observed `0x0100`
condition. A sparse V06 send contains only `0x0040` because the sender adds
that bit even when no rich record was rebuilt.

On successful transmission, the sender clears the pending flags and V06
bitmap but does not erase every copied data byte. Consequently a later sparse
packet may retain old non-zero bytes while carrying only the current `0x0040`
bitmap. This explains the captured rich-body/`0x40` B variant without treating
the retained bytes as a new lifecycle command.

The captured B0/C sequence distinction is also direct: content offset 2 is
incremented after a successful V06 send. It is not a cold-boot/wake opcode.

## Reset behavior

`OnDeviceReset` at `0x1800981e0` reaches `FUN_18008c2a0` through
`FUN_18008ef40`. The reset path reinitializes feedback state, obtains current
display/hinge data, queues display-state feedback, and selects the applicable
FeedbackManager version. It does not replay a single captured 63-byte packet.

## Driver consequences

1. A static full A, B or C replay cannot provide Windows parity. The packets
   contain display, hinge, persistent-host, pen/provider and sequence state.
2. The non-zero tail in the complete KDNET dump is real, but much of it is
   host feedback and some bytes may be retained from an earlier rich update.
3. A Linux heat-only driver should not invent pen, touchpad, hinge or provider
   state merely to reproduce a Windows capture. It should first establish
   which minimum feedback the panel actually requires.
4. Phase 72's short `8e 02` exchange remains an empirical hardware result, not
   a reconstruction of this Windows producer.
5. The next static target is the ARC firmware consumer of Output Report
   `0x09`, especially the subtype dispatch and which V06 validity bits affect
   raw Heat delivery. No production driver change is justified until that
   consumer trace agrees with the host-side evidence.

## Firmware-side corroboration

The matching firmware's appended logger dictionary names display/stitching/
hinge feedback, V03 and V06 pen feedback, and V09 touchpad-threshold feedback.
Its engineering CLI separately exposes display state, hinge angle, FastHostId,
and PRE_OS versus normal full-frame report mode. These independent names agree
with the fields recovered above, but do not by themselves map an A1/A5 subtype
to a particular ARC handler. The exact resource layout and evidence boundary
are documented in
[FIRMWARE_RESOURCE_CONTAINER.md](FIRMWARE_RESOURCE_CONTAINER.md).
