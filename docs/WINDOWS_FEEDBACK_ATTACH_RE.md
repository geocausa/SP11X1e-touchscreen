# Windows feedback attach call graph

## Result

The matching ARM64 `TouchPenProcessor0C83.dll` proves that the initial A1 and A5
report-`0x09` records are deliberately emitted by the Windows device-attach
path.  It also proves that an earlier Claude note describing report `0x09` as a
`0xff00` wrapper containing Linux-style live-contact records is incorrect.

Binary identity:

```text
615a28136f14678298dcd9f009c9295456a9e7ce878717b58d371d343b4c7132  TouchPenProcessor0C83.dll
```

Addresses below use preferred image base `0x180000000`.  The analysis is
reproducible with `tools/ghidra/ListCallers.java` and Ghidra's decompiler.

## Exact cold-attach call chain

Exported `SurfaceHeatProcessor::OnDeviceAttached` at `0x180097a40` calls
`FUN_18008d2d8` exactly once when it creates the first device state.  Despite an
earlier note calling this the per-frame handler, `FUN_18008d2d8` is the large
first-attach initializer.  Its tail is:

```text
FUN_180060e30(feedback, device, provider)   initialize FeedbackManager
...
FUN_180070fe0(posture, region=0, enabled=1, force=0)
FUN_1800615c8(feedback, force=0)            send pending A1
FUN_180061988(feedback, force=1, device=0)  select V03/V06; send initial A5 here
```

`FUN_180070fe0` updates the per-region display bitmap and calls
`FUN_180062af0`, which queues these A1 fields:

- display bitmap;
- stitching flag;
- hinge angle;
- optional posture/provider state.

`FUN_180061278` then writes `8e a1` and transmits exactly 63 content bytes.
FastHostId is already present at content offset 40.

On this SP11 the version selector in `FUN_180061988` takes the V06 path
`FUN_180061ec8`.  The initial forced call:

- writes `8e a5`;
- starts with sequence zero;
- adds current-feedback flag bit 1;
- copies persistent FastHostId to content offsets 39–40;
- unconditionally adds V06 validity bit `0x0040` at offsets 46–47;
- sends exactly 63 content bytes.

With captured provider values `(display=1, stitching=0, hinge=0x0190,
FastHostId=0x0190)`, the recovered serializers produce byte-for-byte the two
cold KDNET records:

```text
b2cae0b35eeb4fee62858ee05edfa2a626b48fe1ef14d38b383642d337504008  A1 63-byte content
f29901ec43a8efc1058e3242f59bdd8e627faf7e71f0fb1f6ca6df946f8a3a31  A5 63-byte content
```

This is stronger than copying those byte strings: it recovers why each
non-zero field exists and which values must come from platform providers.

## Later calls and cadence

`SurfaceHeatProcessor::PostProcessHeatmap` at `0x180098640` calls
`FUN_18008f358`, whose exact sequence is:

```text
FUN_180062270(feedback, device)            send pending A0
FUN_180061278(feedback, device, force=0)   send A1 only when pending
FUN_180061988(feedback, force=0, device)   send selected V03/V06 only when pending
```

This is a feedback drain point after a frame, not proof that Windows sends A1
and A5 for every Heat frame.  The senders test pending flags and return without
transmitting when nothing changed.  Display enable/disable, hinge-angle, and
stitching callbacks independently queue/send A1.  Reset explicitly reinitializes
the manager, rebuilds posture state, sends A1, and invokes the version-selected
feedback sender.

## Corrections to the Claude implementation note

`/home/geoca/Documents/CLAUDE/FEEDBACK_0x09_IMPLEMENTATION_SPEC.md` is useful as
a list of function addresses, but these claims must not be imported:

1. `FUN_18008d2d8` is not the per-frame contact classifier; it is reached from
   `OnDeviceAttached` and performs first-device initialization.
2. A1 is display/posture feedback, not the pen record.
3. A5 is the V06 feedback record and its rich builder is pen/provider-oriented;
   it is not proven to contain Linux contact IDs and coordinates.
4. `0xff00` in `FUN_180060ac8` is the HID Usage Page used to resolve Usage
   `0xc9` to Output Report `0x09`.  It is not an extra `0xff00` metadata-section
   wrapper placed around the 63-byte HID content.
5. The presence of feedback drain calls in `PostProcessHeatmap` does not mean a
   packet is emitted on every frame; all relevant senders are pending-gated.

Consequently the Claude v9 guessed per-contact report body has no Windows
parity basis.  Its hardware result cannot validate that field map.

## Driver boundary

The parity path now contains recovered A1/A5 serializers.  Their inputs are
read-only module parameters and default to unavailable (`-1`), so no feedback
is transmitted accidentally.  An isolated boot may supply the four values from
this exact machine's complete capture.  After A1, the driver strictly requires
the observed `DATA 0xa0={01}` response, emits initial A5, sends exact
`SET_FEATURE 0x05={01}`, and stops again before the independently scheduled
device-config owner issues `GET_FEATURE 0x70`.

That second stop remains intentional because the following device-config owner
is independently scheduled.  The Heat-side activation itself is now recovered:
TouchPenProcessor calls the Feature-`0x05` path **Switch Mode Feedback**,
resolves vendor usage `0xff00:0x00c8`, hard-codes value `1`, and sends it only
when its FeedbackManager is enabled during Heat initialization.  A normal
initializer explicitly requests that switch.  The fresh Windows restart trace
then enters continuous 3,636-byte Heat streaming 163.965 ms after `SET_FEATURE
0x05={01}`.  The later `GET_FEATURE 0x70` still belongs to the separately
scheduled pen auto-bonding owner, so neither the older ~471 ms cross-owner gap
nor the fresh 163.965 ms switch-to-Heat interval should be copied into Linux as
a fixed sleep.  See
[WINDOWS_FEATURE05_SWITCH_MODE_RE.md](WINDOWS_FEATURE05_SWITCH_MODE_RE.md).
