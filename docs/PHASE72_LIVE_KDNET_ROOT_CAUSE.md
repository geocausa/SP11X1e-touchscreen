# Phase 72 live KDNET root cause: truncated mode-config feature payloads

Phase 72 resolves, on live hardware, the recovery/init regression that Phases
66-68 narrowed but could not close. It supersedes the guesses that Phases 66-67
made about report `0x09` and about the `SET_FEATURE 0x70` payload. All evidence
here is from a live KDNET session against the Surface Pro 11 target (Win build
26100), single-stepping the shipping Windows stack with resolved hidspi.sys PDB
symbols and full 72-byte (`db L48`) dumps of every
`hidspi!SpbBusWrapper::MultiSpiTransfer` mode-setup write.

## Direct correction of the Phase 66-68 dead end

- Phase 66 replayed an extended Windows sequence and timed out at "its second
  report-09 exchange", and concluded report `0x09` was unsupported.
- Phase 67 removed the `0x09` exchange and fell back to the minimal
  `0x05 -> 0x70 -> 0x56` feature set, sending `SET_FEATURE 0x70` with the
  one-byte payload `g6ts_mode_enable = {0x01}`.
- Phase 68 froze that minimal path as "proven" because it at least reached Heat.

The live capture shows the Phase 66 conclusion was wrong. Report `0x09` IS
supported and IS sent by Windows on every init and every recovery. The Phase 66
timeout was almost certainly caused by sending `0x09` with the wrong payload
and/or wrong surrounding order, not by the panel rejecting `0x09` as a concept.
The Phase 67 fallback then introduced the actual defect that produces the
frequent panel resets: a TRUNCATED mode-config payload (see below).

## The three reset/init paths are distinct (PDB-confirmed)

hidspi.sys PDB symbols name the state machine explicitly:
`HidSpiDeviceV0StateMachine`. It has separate entry paths:
- `ResettingOnStartup`                 = cold boot
- `ResettingOnD3D0`                    = power / standby (D3->D0)
- `ClearingStateOnDeviceInitiatedReset`= panel-initiated (watchdog) reset

The panel-initiated path is our failure mode. Captured live by freezing the
host mid-stream (KDNET break) until the panel watchdog expired, then resuming:
Windows runs `ClearingStateOnDeviceInitiatedReset`, which re-arms the full
FEATURE set (`0x05/0x70/0x56`) plus `0x09` reports, but does NOT re-run the
`0x65` coordinate/axis config (the panel retains axis calibration through a
watchdog reset). Standby-wake is a LIGHTER path (0x09 + COMMAND_CONTENT 0x01,
no full feature handshake) and must NOT be used as a recovery template.

## Root cause: SET_FEATURE 0x70 (and 0x05) payload is truncated

Across cold boot, standby, and device-initiated reset, Windows sends a shared
config parameter block in three writes. Wire-exact (e2 00 20 00 = HID-SPI write
header; then report_type, LE16 content_len, content_id, payload):

    SET_FEATURE  type=3 id=0x05 = 01 <config>
    SET_FEATURE  type=3 id=0x70 = 01 <config>        (6 bytes total)
    OUTPUT_REPORT type=5 id=0x09 = 8e <config>       (63-byte report)
    SET_FEATURE  type=3 id=0x56 = bc e6 4a 2e 86 78 00   (fixed handshake token)

where <config> is derived (see next section), observed as:
    variant A: a1 01 00 90 01
    variant B: a5 00 02

Cold boot additionally sends OUTPUT_REPORT id=0x65 axis config, e.g.
`00 00 12 a0 89 14 00 3f ff ff ff ff 04 04 75` (0x3fff = 16383 axis max).

Our driver (phase55/modules/g6ts_biosref.c, g6ts_full_reinitialize_locked):
    stage 4: SET_FEATURE 0x05 = g6ts_mode_enable = {0x01}        <-- TRUNCATED
    stage 5: GET_FEATURE 0x70  (response validated then DISCARDED)
    stage 6: SET_FEATURE 0x70 = g6ts_mode_enable = {0x01}        <-- TRUNCATED
    stage 7: SET_FEATURE 0x56 = g6ts_mode_handshake
                             = {bc e6 4a 2e 86 78 00}            <-- CORRECT (exact match)

We send only the leading `0x01` and drop the 5-byte <config> tail on BOTH 0x05
and 0x70, and we never emit the `0x09` output report carrying `8e <config>`.
The panel is told "enable" but never receives the mode configuration
parameters, so it comes up in an under-configured NORMAL/heat mode that streams
for roughly 300 ms and then trips its own watchdog. Because init and recovery
share this same function, every recovery re-installs the same under-configured
mode, which is why one reset cascades into a swarm.

This is consistent with every prior live observation in this repo's phase notes
and the July live-trace session: host DMA path clean, GPI ring empty at the
moment of reset, controller active, completion accounting correct, load
dependent, ~300 ms post-recovery survival.

## The config is DERIVED, not a fixed constant

<config> is not constant: it is `a1 01 00 90 01` when 0x09 variant A is active
and `a5 00 02` when variant B is active, and Windows reads GET_FEATURE 0x70
immediately before writing SET_FEATURE 0x70 (matches the Ghidra
RtlQueryFeatureConfiguration re-derivation in the recovery worker). The correct
fix therefore is NOT to hardcode a 6-byte constant. It is:

1. stage 5 already issues GET_FEATURE 0x70; STOP discarding its response and
   retain the returned config bytes (currently g6ts_expect_response only checks
   class/id/len and drops the payload).
2. stage 6: write SET_FEATURE 0x70 = {0x01, <config-from-GET>} (echo the panel's
   own bytes back, prefixed with 0x01), instead of {0x01}.
3. stage 4: likewise SET_FEATURE 0x05 = {0x01, <config>}.
4. emit OUTPUT_REPORT 0x09 = {0x8e, <config>} as Windows does (both variants in
   the observed order A then B).
5. keep SET_FEATURE 0x56 = {bc e6 4a 2e 86 78 00} (already correct).
6. cold-boot only: also send the 0x65 axis/coordinate config.

## Recovery mechanics (secondary, address only if resets persist after the fix)

Windows' device-initiated-reset recovery is software-only (no HW power-cycle in
the hidspi recovery state machine; the panel keeps axis config), event-gated
(KeSetEvent releases the data path only after recovery completes) and verified.
Our g6ts_full_reinitialize_locked begins with a full g6ts_power_off/power_on
GPIO+ACPI cycle and resumes streaming immediately with no readiness gate. That
is heavier than Windows and ungated, but is likely not the primary defect. Fix
the 0x70/0x05 config truncation FIRST; revisit the HW power-cycle and add a
readiness gate only if resets persist.

## Two-bug framing (validated)

- BUG #1 (panel resets too often under load): root cause = truncated mode config
  (0x70={01} vs {01 <config>} plus missing 0x09), so the panel never enters a
  fully-established NORMAL mode. Fix = deliver the full derived config.
- BUG #2 (recovery cascade / swarming): our recovery re-installs the same broken
  mode each time, so each recovery yields another ~300 ms session. Fixing BUG #1
  is expected to break the cascade because recovery will finally install a stable
  mode. Residual gating/HW-cycle differences are BUG #2's secondary factors.

## Exact code targets

phase55/modules/g6ts_biosref.c:
- line ~115  g6ts_mode_enable = {0x01}        -> becomes {0x01, <config>} (derived)
- line ~1852 stage 4 SET_FEATURE 0x05 payload -> {0x01, <config>}
- line ~1861 stage 5 GET_FEATURE 0x70          -> RETAIN response bytes (add parse)
- line ~1869 stage 6 SET_FEATURE 0x70 payload -> {0x01, <config>}
- add        OUTPUT_REPORT 0x09 = {0x8e, <config>} (variants A, B) around stage 6
- line ~1882 stage 7 SET_FEATURE 0x56          -> unchanged (correct)
- g6ts_expect_response currently discards payload; add a variant that returns the
  response body so stage 5 can capture <config>.

## Validation plan (reversible; known-good phase68 untouched; phase70/71 pattern)

1. Read-only: cold-boot phase68, sustained touch several minutes, count resets to
   establish the baseline BUG #1 rate (prediction: cold boot also resets, since it
   uses the same truncated path).
2. One isolated GRUB entry + git branch implementing the derived-config fix.
3. Deploy, sustained-touch test, count resets vs baseline; log results; push facts.

## Provenance

Live KDNET capture archived as sp11_clean_3events.log (host:
C:\Users\SurfacePro7\Documents\KDNET\). Windows target observed read-only via
debugger; nothing written to the target. No change yet to this tree or the Linux
device. Desktop working notes: SP11_DRIVER_DISCREPANCY_AUDIT.md,
SP11_WINDOWS_RECOVERY_DISSECTION.md, SP11_DEFINITIVE_FINDINGS.md.

## VALIDATION RESULT (2026-07-17, on-device)

Deployed the mode_config_fix on the isolated sp11-phase72 GRUB entry
(g6ts_biosref.mode_config_fix=1), known-good phase68 untouched.

Boot log:
  phase72: GET_FEATURE 0x70 config len=1 bytes=02
  phase72: SET_FEATURE 0x70 derived len=2 bytes=01 02
  phase72: OUTPUT_REPORT 0x09 len=2 bytes=8e 02
  touch controller initialized recoveries=1 resets=0   (1 = normal boot init)

Outcome after ~5h50m uptime including deliberate stress/crash attempts:
  panel resets = 0.

Baseline before the fix: a reset every 2-7s under sustained touch (dozens/min).
At that rate ~5h50m would have logged thousands of resets. Observed: zero.
=> The reset storm is eliminated.

Note on the config bytes: the Linux panel's GET_FEATURE 0x70 returns a single
byte 0x02 (not the a1 01 00 90 01 seen on the Windows target, whose panel was
already in a richer configured state). What mattered was ECHOING the panel's own
returned byte (send {0x01,0x02}) instead of the hardcoded {0x01}. The derive-and-
echo approach is therefore the correct general fix even though the exact config
byte differs from the Windows capture. Root-cause mechanism (truncated/wrong
mode-config feature payload) confirmed.
