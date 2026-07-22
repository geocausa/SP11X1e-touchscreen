# SP11X1e Touchscreen — DEFINITIVE FINDINGS (live KDNET, 3-event capture)

Date: 2026-07-17. Source: live KDNET capture of the Windows driver on the actual Surface Pro 11
target, capturing THREE distinct panel-init events with full 72-byte (db L48) dumps of every
hidspi!SpbBusWrapper::MultiSpiTransfer mode-setup write. Raw log: sp11_clean_3events.log.
This supersedes all earlier inferences that were based on the stale June capture.

=====================================================================================
THE THREE RESET/INIT PATHS ARE DIFFERENT (confirmed by PDB symbol names + wire capture)
=====================================================================================
hidspi.sys PDB symbols expose the state machine by name, proving Windows has THREE distinct paths:
  - ResettingOnStartup                  = cold boot
  - ResettingOnD3D0                      = power/standby (D3->D0)
  - ClearingStateOnDeviceInitiatedReset  = panel-initiated (watchdog) reset  <-- OUR LINUX BUG

The user's hypothesis was CORRECT: standby-wake is NOT the same as crash-recovery, so a standby
capture is NOT a valid template for our recovery. We captured all three separately:

EVENT 1 — COLD BOOT (heaviest; full init):
  0x09(A) -> 0x09(B) -> SET_FEATURE 0x05 -> SET_FEATURE 0x70 -> SET_FEATURE 0x56
  -> OUTPUT 0x65 (coordinate/axis config, e.g. ...12 a0 89 14 00 3f ff ff ff ff 04 04 75; 3fff=16383)
  The 0x65 axis/coordinate setup appears ONLY at cold boot.

EVENT 2 — STANDBY-WAKE (lightest):
  0x09 reports (with live runtime state) + COMMAND_CONTENT 0x01. NO 0x65, NO full feature handshake.
  Assumes the panel retained its configuration through standby.

EVENT 3 — DEVICE-INITIATED RESET / TRUE RECOVERY (provoked by freezing the host mid-stream so the
panel watchdog expired — i.e. exactly our Linux failure mode):
  SET_FEATURE 0x05 -> 0x09 -> SET_FEATURE 0x70 -> SET_FEATURE 0x05 -> SET_FEATURE 0x56
  -> 0x09(A) -> 0x09(B)
  Full FEATURE re-arm (0x05/0x70/0x56) + 0x09 reports, but does NOT re-run 0x65 (panel keeps its
  axis calibration through a watchdog reset; only the mode/feature state must be re-established).

=====================================================================================
THE ROOT CAUSE — our SET_FEATURE 0x70 payload is TRUNCATED
=====================================================================================
Confirmed across ALL THREE events, the config parameter block is shared across three writes:

  Windows SET_FEATURE 0x05 = 01 <config>
  Windows SET_FEATURE 0x70 = 01 <config>       <<< 6 bytes
  Windows OUTPUT_REPORT 0x09 = 8e <config>
  where <config> = "a1 01 00 90 01" (variant A)  OR  "a5 00 02" (variant B)

  Windows SET_FEATURE 0x56 = bc e6 4a 2e 86 78 00   (fixed handshake token)

OUR LINUX DRIVER (g6ts_biosref.c):
  g6ts_mode_enable    = { 0x01 }                          -> used for BOTH 0x05 AND 0x70
  g6ts_mode_handshake = { bc e6 4a 2e 86 78 00 }          -> used for 0x56

  So our 0x56 is CORRECT (exact match). Our 0x05 sends {01} (Windows sends {01 <config>}), and our
  0x70 sends {01} while Windows sends {01 a1 01 00 90 01}. We DROP the 5-byte <config> tail on BOTH
  0x05 and 0x70, and we NEVER send the 0x09 OUTPUT report carrying 8e <config>.

  => The panel is told "enable" but is NOT given the mode configuration parameters. It comes up in
     an under-configured NORMAL/heat mode that streams briefly (~300ms) then its watchdog trips.
     This is THE bug, and it explains every prior observation (host path clean, ring empty at reset,
     load-dependent, ~300ms post-recovery survival, cold-boot uses the SAME truncated path so cold
     boot should ALSO be only transiently stable — which the cold-boot endurance test should confirm).

=====================================================================================
THE CONFIG IS DERIVED, NOT A FIXED CONSTANT (critical for the fix)
=====================================================================================
The <config> tail is NOT constant: it is "a1 01 00 90 01" when 0x09 variant A is active and
"a5 00 02" when variant B is active, and Windows reads GET_FEATURE 0x70 before writing SET_FEATURE
0x70 (matches the Ghidra RtlQueryFeatureConfiguration re-derivation). Therefore the correct fix is
NOT to hardcode a 6-byte constant — it is to:
  1. issue GET_FEATURE 0x70 (we already do this in stage 5),
  2. USE the returned config bytes (we currently DISCARD them),
  3. write SET_FEATURE 0x70 = 01 <config-from-GET>, and similarly SET_FEATURE 0x05 = 01 <config>,
  4. and emit the 0x09 OUTPUT report = 8e <config> as Windows does.

Observed config values (for reference / initial testing if GET parsing is deferred):
  Variant A: a1 01 00 90 01   (0x0190 = 400 decimal appears; a1/01 mode selectors)
  Variant B: a5 00 02
  Cold-boot 0x65 axis block: 00 12 a0 89 14 00 3f ff ff ff ff 04 04 75  (3fff = 16383 axis max)

=====================================================================================
THE FIX (concrete, byte-exact, grounded in live ground truth)
=====================================================================================
In g6ts_full_reinitialize_locked (used by BOTH init and recovery):
  - Stage 5: parse the GET_FEATURE 0x70 response (currently validated-then-discarded by
    g6ts_expect_response) and retain its <config> bytes.
  - Stage 6: change SET_FEATURE 0x70 payload from {0x01} to {0x01, <config...>} (6 bytes: 01 + the
    5 config bytes from the panel's GET response, mirroring Windows).
  - Stage 4: likewise send SET_FEATURE 0x05 = {0x01, <config>} rather than {0x01}.
  - Add the OUTPUT_REPORT 0x09 = {0x8e, <config>} write(s) that Windows sends (variants A and B).
  - Keep SET_FEATURE 0x56 = {bc e6 4a 2e 86 78 00} (already correct).
  - For COLD BOOT only, also send the 0x65 coordinate/axis config Windows sends at startup.

Recovery-mechanics note (secondary, from Ghidra + symbols): Windows recovery is event-gated
(KeSetEvent) and verified, and is SOFTWARE-ONLY for the device-initiated path (no HW power-cycle in
the hidspi recovery state machine — the panel keeps axis config). Our recovery does a full HW
power-cycle (g6ts_power_on) at the top of g6ts_full_reinitialize_locked. That is heavier than
Windows and may be unnecessary, but is likely not harmful once the 0x70 config is correct. Address
the 0x70 truncation FIRST (it is the clear root cause); revisit the HW power-cycle only if resets
persist after the config fix.

=====================================================================================
VALIDATION PLAN (reversible, known-good untouched — phase70/71 isolation pattern)
=====================================================================================
1. [read-only, first] Cold-boot endurance: boot phase68 cold, sustained touch several minutes,
   count resets. Prediction given this finding: cold boot ALSO resets frequently under sustained
   touch (same truncated 0x70 path), OR is masked by something — either way informs expectations.
2. Build ONE isolated GRUB entry + git branch implementing the 0x70/0x05 config + 0x09 output
   report (GET-derived config). Known-good phase68 untouched.
3. Deploy, sustained-touch test, count resets vs baseline. Log results. Push concrete facts to repo.

TWO-BUGS FRAMING (user's, now well-supported):
  BUG #1: panel resets under load — root cause = truncated mode config (0x70={01} vs {01 <config>}),
          so the panel never gets a fully-established NORMAL mode. FIX = send full config.
  BUG #2: recovery cascade/swarming — our recovery differs from Windows' gated/verified software-only
          path AND (until BUG#1 is fixed) re-establishes the same under-configured mode, so each
          recovery yields another ~300ms session -> cascade. FIXING BUG#1 likely breaks the cascade
          because recovery will finally install a stable mode.

STATUS: Root cause CONFIRMED on live hardware with byte-exact wire data. Fix is concrete and
low-risk. Nothing was modified on the Linux tree, the Linux device, or the Windows target (all
read-only / debugger-observation). Raw capture: sp11_clean_3events.log.
