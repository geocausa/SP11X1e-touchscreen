# Open Questions Audit — 2026-08-04

This audit is the current closure matrix for the Surface Pro 11 `MSHW0485`
G6 touchscreen work.  It intentionally separates questions that are genuinely
open from older phase notes whose original uncertainty has since been resolved.

The production Linux baseline remains Phase 91.  Nothing in this audit changes
that hardware-validated control.

Status vocabulary:

- **RESOLVED** — evidence is sufficient to stop treating the item as an open
  protocol/reverse-engineering question.
- **NARROWED** — the mechanism is substantially recovered, but one specific
  boundary is still missing.
- **VALIDATION-BLOCKED** — implementation or theory exists, but a safe labelled
  hardware observation is still required.
- **ENGINEERING** — not primarily a reverse-engineering mystery; implementation
  work remains before it can replace the Phase 91 behavior.

## Current matrix

| area | status | current evidence boundary | next useful action |
|---|---|---|---|
| Feature `0x70` meaning | **RESOLVED** | device-config / Slim Pen 2 MPP 2.6 host/OOB auto-bonding capability; it is not the touch full-frame selector | keep it out of touch report-mode hypotheses |
| Feature `0x05` Windows meaning | **RESOLVED** | HEAT collection Feature usage `0xff00:0x00c8`; Windows constructs `{05,01}`; HeatCore mode enum is `Disabled=0`, `Heatmap=1`; Windows attach sends `SET_FEATURE 05=01` before continuous 3636-byte Heat | retain the existing Feature-05 proof; do not infer current mode from `GET_FEATURE 05`, whose live readback can be `00` while Heat is active |
| Windows HEAT user-mode owner | **RESOLVED** | `heat.inf` grants the DWM security group access; restart evidence shows `dwm.exe` launches `ISM.exe`; the new ISM loads `hid.dll`, `HeatCore.dll`, and the exact `TouchPenProcessor0C83.dll`; ISM owns COL02 HEAT registry state | treat `DWM -> ISM -> HeatCore + TouchPenProcessor -> COL02` as the user-mode ownership chain; this does not by itself identify every individual HID API caller |
| HeatCore TraceLogging provider | **RESOLVED** | provider name `Microsoft.Windows.Heat.HeatCore` maps to GUID `{55A5DC53-E24E-5B53-5B52-EA83A0CC4E0C}`. A corrected restart trace emits HeatCore events and `HeatDllLoadResult` for the exact 0C83 processor DLL | use this provider for targeted lifecycle/debug captures; absence of a particular optional event is not evidence that its code path did not run |
| panel production consumer for Feature `0x05` | **NARROWED** | host and engineering-mode semantics agree, but the ARC production HID SET-feature dispatcher has not been directly linked from usage `0xff00:0x00c8` / report `0x05` to the same internal report-mode state as `SetReportMode` / `GetCurrentReportMode` | continue structure-driven ARC dispatcher recovery; literal searches and bounded-indirect heuristics have produced only false/ambiguous candidates |
| report `0x09` requirement for basic Heat | **RESOLVED: NOT REQUIRED** | Windows attach emits dynamic A1/A5 FeedbackManager control-plane records, but the cold-boot-validated Phase 62 Linux tree (`e35fbc4`) contains no `0x8e` payload and no client-side report-09 send. That boot entered Heat mode and streamed >1,500 decoded frames. Phase 72 later also worked with only the two-byte `8e 02` record. Therefore neither full A1/A5 nor any report-09 transaction is required to activate basic Heat streaming | keep report-09 out of the minimal Heat activation contract; only implement feedback if a separate display/hinge/pen/provider behavior requires it |
| natural panel-initiated reset | **VALIDATION-BLOCKED** | host-timeout resets, descriptor re-enumeration, and recovery have been captured; no spontaneous panel-originated reset has been observed | low-overhead long-duration reset-only Windows capture / KDNET soak; classify origin before changing reset policy |
| suspend/resume implementation | **RESOLVED (code)** / **VALIDATION-BLOCKED (hardware)** | driver has explicit system-sleep PM callbacks: suspend cancels work/IRQ/requests and powers off; resume calls the proven reinit path with fallback recovery | do not redesign until tested; hardware suspend validation remains blocked by prior platform-level suspend instability |
| detector geometry / connected components | **RESOLVED** | threshold, 68x46 column-major topology, four-neighbor components, centroid/covariance/eigenshape/orientation and descriptor normalization are recovered and represented offline | no protocol RE required |
| tracker assignment / lifecycle / output record | **RESOLVED statically** | Windows assignment scale, state machine, history, duplicate merge, 0x38-byte output record, normal/split record handling, edge/corner flags and output construction are substantially recovered | remaining gap is live/private intermediate ground truth, not the broad algorithm |
| four classifier class meanings | **NARROWED** | exact four-class scoring/argmax is recovered. DLL telemetry vocabulary contains `Finger`, `FingerAwareness`, `Smear`, `SmearAwareness`, and `Bunch`, but no direct class-index mapping is proven | trace the telemetry call/table that consumes class IDs, or obtain labelled Windows intermediate data; do not assign human labels by string order |
| palm / edge semantics | **VALIDATION-BLOCKED** | Windows contains radial/border palm rejection and edge/corner logic; static control flow is known in substantial detail | collect labelled physical palm, edge, corner and close-crossing captures with synchronized ground truth |
| Linux finger pressure | **RESOLVED / NOT A WINDOWS TOUCH TARGET** | HeatCore Touch capability validation requires EndRange/InRange/Button/Confidence/X/Y/Width/Height and explicitly rejects Invert/Eraser/Barrel/**Pressure**/Twist/Tilt/PenId for Touch. Phase 91 not exposing `ABS_MT_PRESSURE` is therefore consistent with the Windows HEAT finger-touch model. A private tracker scalar or force-related channel must not be renamed public Touch pressure without separate proof | do not add `ABS_MT_PRESSURE` for Windows finger-touch parity; keep any internal force/scalar research separate from the public Touch ABI |
| Linux contact shape | **NARROWED / ENGINEERING** | Windows Touch Geometry is now proven end-to-end at the public ABI: HeatCore emits 32-bit Width/Height HID usages; `HeatTouchContactNew` carries Width at `+0x14` and Height at `+0x18`; the processor computes raw dimensions as inclusive component extents `max_x-min_x+1` / `max_y-min_y+1` and may smooth them per track. The exact private TPP adapter copying smoothed track dimensions into the public 0x20 contact is still anonymous because the exact processor PDB is not published | use [WINDOWS_TOUCH_CONTACT_ABI_RE.md](WINDOWS_TOUCH_CONTACT_ABI_RE.md) as the static baseline; recover/measure the active smoothing profile and map Windows Width/Height units deliberately onto Linux touch-major/minor, then validate labelled contacts |
| merged-finger separation | **ENGINEERING + VALIDATION** | Windows candidate/tracker/duplicate-merge behavior is substantially recovered, but the production Linux path does not reproduce the whole pipeline and close contacts remain under-validated | stage the recovered lifecycle/assignment/output pipeline coherently and test labelled close/crossing contacts rather than tuning another proximity heuristic |
| end-to-end Windows intermediate oracle | **NARROWED / CAPTURE-BLOCKED** | raw Heat is available and the static pipeline is largely recovered; private candidate/track/output buffers are not serialized in ordinary captures | use debugger/TraceLogging instrumentation only if it can expose stage outputs without destabilizing the panel |
| provider/profile rectangles and remaining runtime context | **NARROWED** | static consumers are known, but some provider-owned live values and per-frame context flags are not PSDB constants | mine HeatCore/processor TraceLogging and provider state before inventing Linux constants |
| Phase 72 short-sequence success | **HISTORICAL / LOW PRIORITY** | Phase 72 was hardware-working but its short `8e 02` feedback and derived sequencing are not a faithful Windows attach replay | only isolate if it informs simplification of the Phase 91 init; do not regress the current control to answer a historical curiosity |
| kernel/version portability | **ENGINEERING** | Phase 91 is validated only on the current Snapdragon/GPI-DMA baseline and still depends on Qualcomm/SPI transport details and project-specific integration | make a dependency inventory, split generic G6 protocol from Qualcomm transport, then validate each additional kernel separately |
| upstream/mainline readiness | **ENGINEERING** | functionality is research-grade and hardware-specific; pressure/shape/suspend validation and transport abstraction remain incomplete | defer upstream API cleanup until hardware semantics and transport boundaries are stable |
| pen | **OUT OF SCOPE** | intentionally excluded from the current finger-touch objective | do not let pen-specific behavior block touchscreen completion |

## New Windows owner evidence

A Procmon/PnP restart sequence closes a previously fuzzy ownership question.
Around COL02 teardown the old `ISM.exe` closes the HEAT registry keys under the
`HID\\MSHW0485&Col02` device parameters.  `dwm.exe` then launches a replacement
`ISM.exe`, which loads `hid.dll`, `HeatCore.dll`, and the exact installed
`TouchPenProcessor0C83.dll`.  Combined with `heat.inf` granting access to the
DWM user group, the supported user-mode chain is:

```text
DWM -> ISM.exe -> HeatCore.dll + TouchPenProcessor0C83.dll -> COL02 HEAT HID collection
```

This is process/module ownership evidence.  It should not be overstated as a
per-call proof that a particular function inside one module issued every
`HidD_*` request.

## Correct HeatCore TraceLogging provider

The deterministic EventSource provider ID is:

```text
Microsoft.Windows.Heat.HeatCore
{55A5DC53-E24E-5B53-5B52-EA83A0CC4E0C}
```

The earlier byte-swapped GUID produced an empty trace.  A corrected controlled
PnP restart produced real HeatCore events and left `ACPI\\MSHW0485` in status
`OK`.  The trace includes `HeatDllLoadResult` identifying the exact installed
0C83 processor DLL.  It also records `HeatDevice::SendDeviceCommand*` errors
during restart teardown/reconstruction; those lifecycle errors are not treated
as a steady-state touch fault.

Evidence files remain outside Git under:

```text
C:\Users\Geoca\Documents\SP11X1e-evidence\2026-08-04\heatcore-restart2.etl
C:\Users\Geoca\Documents\SP11X1e-evidence\2026-08-04\heatcore-restart2.csv
```

## Feature `0x05`: remaining panel boundary

The Windows side is no longer an open question.  The unresolved boundary is
specifically inside the ARC firmware production HID dispatcher.

Unsuccessful/static-negative searches are useful constraints:

- literal/report-usage searches do not expose an obvious `0xff00:c8 -> 0x05`
  handler;
- scanning 1,341 ARC functions for combinations of `0xff00`, `0xc8`, and `0x05`
  produced one weak allocator/control-flow false positive containing only `5`
  and `200` (`0xc8`), not the full usage tuple;
- bounded indirect-dispatch heuristics produced three unrelated functions
  (format parsing, math/data traversal, and hardware-register configuration);
- apparent packed-table candidates near `0x20031b00/0x20031c00` have not survived
  validation as HID dispatch entries.

Therefore the next ARC step should be provenance-driven rather than another
whole-image literal scan: identify the HID report-registration structure and
follow the SET-feature operation callback path to the report/usage-specific
consumer.

## Classifier semantic vocabulary

String/telemetry mining of the exact installed processor DLL exposed named
classification-latency families including:

- `Finger`
- `FingerAwareness`
- `Smear`
- `SmearAwareness`
- `Bunch`

The production detector itself still computes four class scores and emits the
argmax class `0..3`.  Five telemetry labels therefore cannot safely be mapped
to those four class values by order or intuition.  The labels are useful
semantic vocabulary and a new xref target, but **not** a proven class map.

## Contact-output implementation boundary

The production Phase 91 input device currently registers only multitouch X/Y.
It does not advertise `ABS_MT_PRESSURE`, `ABS_MT_TOUCH_MAJOR`,
`ABS_MT_TOUCH_MINOR`, or `ABS_MT_ORIENTATION`.

Pressure is no longer an open finger-touch parity item.  Direct decompilation
of HeatCore Touch capability validation proves that Touch must provide
EndRange/InRange/Button/Confidence/X/Y/Width/Height while Pressure is in the
set explicitly rejected for Touch.  Generic HeatCore pressure support exists
for other pointer classes, so that result must not be generalized to Pen or
other devices.

Width/Height remain legitimate Touch semantics.  Windows component geometry,
output bounds and shape/history selection are already recovered; the remaining
contact-shape job is to prove the final Width/Height scaling/consumer mapping
and then map that deliberately onto Linux touch-major/minor/orientation fields
with labelled contacts.

## Suspend/resume boundary

System-sleep PM callbacks already exist in the driver.  Suspend marks touch not
ready, cancels RX/reset work, disables IRQ, cancels outstanding requests and
powers the device off.  Resume runs `g6ts_reinit_after_powerup()` and the
existing fallback recovery path.

Consequently suspend/resume should be described as **implemented but not
hardware-validated**, not as absent functionality.  Prior whole-platform
suspend instability means validation should not be mixed into unrelated
protocol work.

## Priority order after this audit

1. Recover the ARC production SET-feature dispatcher far enough to tie Feature
   `0x05` to the internal report-mode state.
2. Isolate the minimum report-`0x09` requirement with one-variable Linux tests,
   without replaying dynamic Windows A1/A5 payloads as constants.
3. Pursue a class-ID-to-semantic-label mapping through processor telemetry/xrefs.
4. Build labelled palm/edge/close-contact datasets and use them to validate the
   recovered Windows processing stages.
5. Add pressure/shape/merged-contact behavior only on experimental branches.
6. Capture a genuine panel-originated reset during a long low-overhead Windows
   soak.
7. Validate system suspend/resume only after the platform suspend path is safe.
8. Refactor protocol-versus-Qualcomm transport dependencies before claiming
   wider kernel or upstream support.

Phase 91 remains the production control throughout.
