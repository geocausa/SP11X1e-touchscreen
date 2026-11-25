# Touch and pen stack audit — 2026-11-24

The requested endpoint is Linux finger multitouch plus pen input and the useful
companion behavior supplied by Windows. **That endpoint has not been reached.**
The new [production-v1 candidate](../production-v1/README.md) completes a bounded
finger-touch cleanup and has runtime finger confirmation. Its driver registers
one touchscreen and contains no pen input device or raw pen receiver.

## Capability and evidence map

| Capability | Current Linux candidate | Remaining acceptance |
| --- | --- | --- |
| HID-over-SPI transport, attach, fault recovery | Implemented; isolated zero-cmdline cold boot (`test6`) and runtime touch have no transport/reset faults | Sustained soak, reset fault injection validation |
| Finger multitouch | Up to 10 slots, tracking, edge snap, merged-finger splitting, duplicate suppression | Keyboard cadence, edge/crossing/slow-drag regressions on final image |
| Contact size, touch pressure | Estimated from heatmap shape/signal | Calibration/accuracy comparison; these are not measured pen force |
| Geometry | Feature 0x06 parsed, 46x68 accepted, physical resolution set | Other panels/geometries unsupported; orientation flags are recorded, not a general orientation transform |
| Power management | OFF by default, asynchronous cold recovery; final Patch 8 cold-booted real `s2idle` + post-wake touch passed (`test7`, 147 ms post-exit init, +1,052 Heat frames, 0 resets); optional SLEEP/warm path | Repeated `s2idle` cycles and battery-draw measurements |
| Firmware-decoded fallback pen (`Col07`, report 0x01) | No Linux decoding/input path | Descriptor-verified packet layout and live pen test in fallback mode |
| Pen alongside HEAT multitouch (`Col02`, vendor section 0xFF00) | No MPP/Hasta receiver, no pen coordinates/events | Raw pen windows, calibration, decoding/state machine, replay oracle and live tests |
| Pen hover/pressure/tilt/barrel/eraser | No Linux event reporting | Valid receiver output, Linux input mapping, limits/units, lift/reset/PM cleanup |
| Pen-aware palm rejection | Finger shape/bezel guards exist; no pen-driven rejection | Valid timestamped pen location/proximity and tested suppression policy |
| Pen ID, battery, Bluetooth adaptation (`Col05`) | No ID/battery decoding or automatic bonding integration | Receiver data, host identity policy, BlueZ/HID integration and actual pen |
| Tactile inking/haptics (`Col0A` and pen BLE) | No implementation | Verified commands, bonded BLE haptics device and application support |
| Dynamic display/posture feedback | Fixed display-on/slate/FastHostId attach values | Display/tablet-state provider, protocol validation and lifecycle tests |
| Touch/pen firmware updates (`Col06` / utilities) | No updater; current touch starts without CFU offers | Separate authenticated/versioned update design; not required for normal touch input |

Windows services and updater traffic are not automatically prerequisites for
Linux input. BLE pairing/haptics involve the Bluetooth stack and applications as
well as the digitizer; not every Windows function belongs in this SPI driver.

## What the new Windows material establishes

The owner's local `SP11-Touch-Driver-RE` documentation describes ten HID
collections, a Feature 0x05 fallback/HEAT mode switch, vendor `0xFF00` CCP records,
MPP 2.6/Hasta digital processing, feedback, BLE adaptation and power management.
It is local research evidence, not hardware acceptance of a Linux driver.

The accompanying C reconstruction was inspected locally. Its pen companion code
contains a fallback `Col07` report converter, CCP record summarizer, pen report
format helpers, BLE address derivation and command builders. It does **not**
implement a DFT-to-position/pressure/tilt receiver or the Hasta digital/state
pipeline. The HEAT plugin does not call such a receiver. Registering an empty pen
input device or interpreting magnitude data as decoded coordinates would not
complete pen support.

The `20/20 PASS` ARM64 report exercises helpers with inputs, including fabricated
pen reports and CCP records. It demonstrates those cases, not a real pen drawing,
pressure calibration, automatic Bluetooth pairing, or haptic output. The owner
has no pen available for live testing as of this audit.

The mode notes say `Col07` firmware-decoded pen is the fallback-mode path and
HEAT uses raw vendor records. Switching to fallback could sacrifice multitouch;
simultaneous firmware pen and HEAT must be demonstrated before relying on it.

## Conflicts that must stay visible

- Feature `0x70` is identified by the new notes as **Col05 host auto-bonding
  capability**, not a touch mode selector. The candidate sends its one-byte
  setup because prior Linux experiments found it prevents watchdog resets.
  Its existing comment claiming this avoids Col05 is therefore too broad.
  That one exchange does not implement BLE bonding or pen support.
- The older repository already contains more precise touch lifecycle/output
  investigations. A new high-level reconstruction or a radius-only palm helper
  is not proof of Windows processing parity. Keep proven facts separate from
  Linux heuristics and untested provider state.
- `test4` proves command/initialization progress; it contains zero touch frames.
  `test5` closes runtime finger operation, `test6` closes isolated zero-cmdline
  cold boot (`sp11-touch-final`), and `test7` closes a single real `s2idle`
  cycle plus post-wake touch on the cold-booted Patch 8 image (147 ms post-exit
  init, +1,052 Heat frames, zero resets). Sustained multi-cycle soak and pen
  support remain open.
- Sleep/OFF are write-only. The helper emulation case called a sleep "Ack"
  does not override the later protocol correction or turn write success into
  a device acknowledgment.

## Concrete work needed to finish pen

1. Use a real compatible pen to obtain matched raw CCP streams and decoded
   Windows pen output: hover, contact, varying force, X/Y tilt, barrel/eraser,
   out-of-range, multiple panel positions and reset/resume. Preserve firmware,
   descriptor, calibration identity and timestamps. Keep captures private.
2. Confirm record versions, frequency/window geometry, calibration and selection
   rules. Recover/test the receiver's position/tilt/pressure path and digital
   framing, error correction, CRC and ID/button/battery assembly against the
   paired recordings. Function names and summary tables are insufficient to
   supply these missing algorithms and calibration values.
3. Independently implement a bounded, kernel-appropriate receiver and explicit
   pen lifecycle. Test malformed frames, lost/reordered windows, duplicate
   timestamps, pen lift and reset/PM. Then add Linux `ABS_X/Y`, pressure, tilt,
   `BTN_TOOL_PEN/RUBBER`, tip and stylus buttons with descriptor-derived units.
4. Add pen-aware palm handling from valid proximity/position data, with stale-pen
   timeout and finger/pen coexistence tests. Do not suppress fingers based only
   on the presence of an arbitrary pen-related CCP record.
5. Treat battery/identity, optional BLE bonding and haptics as separate tested
   integrations. Firmware updating is a separate feature with its own evidence
   and recovery requirements.

`tools/inspect_pen_ccp.py` can inventory bounded vendor streams offline. It emits
record metadata and known general fields, **not pen coordinates**, and is not a
runtime dependency. Its synthetic tests demonstrate parsing boundaries only.
This makes the missing evidence inspectable without pretending to supply a pen
receiver.

An offline clean-room mathematical specification of the MPP 2.6 ("Hasta")
receiver algorithms (CCP `0x5B`/`0x5C`/`0x5F`/`0x62` layouts, `WindowType 6..11`
slot allocation, 3-point/5-point antenna centroids, tip-to-ring tilt/azimuth and
HID Cartesian projection, 10-entry frequency pressure + hybrid 10-bit digital
unwrapping, Extended Hamming(16,11) odd-parity check, ITU-T CRC-4 `x^4+x+1`,
buttons/battery/Pen ID reassembly, and azimuth-sector radial palm rejection) is
documented in [PEN_HASTA_RECEIVER_SPEC.md](PEN_HASTA_RECEIVER_SPEC.md) with an
offline reference prototype in `tools/pen_hasta_prototype.py`. **Both remain
unvalidated against a physical Surface Pen** and are not wired into the Linux
kernel driver; real pen captures and live verification are still required.

## Provenance and publication boundary

The source snapshot and eight patches come from the owner's GPL-2.0 kernel work;
the classifier header already exists byte-for-byte in the public repository.
No decompiled OEM code is copied into this update. Windows DLL/SYS/firmware,
recovered C exports, reconstructed Windows plugin sources and raw Windows traces
remain local. Linux validation stats are included separately. Protocol findings
above are independently summarized; no new vendor implementation is published.

A hashed local-evidence index is included in
[production-v1/windows-evidence-index.json](../production-v1/windows-evidence-index.json).
It records the documents/reconstruction inspected without including their data.
