
---

## UPDATE 2026-07-16 (pm, cont.7) — FULL WINDOWS RECOVERY SEQUENCE + "does Windows glitch too?"

### Full Windows software-recovery call chain (HidSpiCx.sys)
  FUN_14000a360 (recovery handler: sets mode ctx+0x20=7, KeSetEvent gate, WPP "Recovered" latch)
    -> FUN_140006010 (checks state flag DAT_140017620; if bit clear -> worker with class 3)
      -> FUN_140006050 -> FUN_140006c10 (recovery state machine):
           if state bit1 clear -> FUN_1400068d0 (THE RE-ARM, see below)
           then for class==3/4 -> FUN_1400066c0 + FUN_140006b98 (class-specific apply)

### FUN_1400068d0 = the real re-arm, and the KEY difference vs our driver
  - Calls RtlQueryFeatureConfiguration and RE-DERIVES the full capability/mode mask from the panel's
    CURRENTLY REPORTED feature bits (bit assembly into 0x9c1 / 0x800 / 0x400 / 0x40 / <<10 fields).
  - Commits the new mode word via an atomic compare-exchange loop (while *param_1 != uVar9).
  - i.e. Windows recovery REBUILDS the operating mode FROM THE PANEL'S LIVE FEATURE QUERY, then
    atomically commits it. It does NOT replay a fixed handshake.

### OUR driver by contrast (g6ts_full_reinitialize_locked)
  - Replays FIXED hardcoded byte arrays: g6ts_mode_enable (SET_FEATURE 0x70) and g6ts_mode_handshake
    (SET_FEATURE 0x56). Static payloads, not re-derived from a live feature query.
  - Resumes IRQ/streaming immediately after, with NO event gate and NO post-recovery verification
    that the panel reached stable streaming state.

### DOES WINDOWS GLITCH AS OFTEN AS WE DO?  ->  NO. And the binary itself proves the intent:
  - The "Recovered after power-on timeout" log sits behind a ONE-SHOT LATCH (ctx+0x9c, set once then
    cleared). You only put a de-duplicating one-shot on an event you expect to be RARE.
  - Recovery is coordinated (KeSetEvent gates the stream) and verified (reads worker status before
    declaring success). This whole structure is built for OCCASIONAL recovery, not a per-second loop.
  => Windows DOES see the occasional panel-initiated reset (the panel hardware genuinely does this),
     but it recovers cleanly ONCE and does NOT cascade.

### THEREFORE — why do WE crash so often (the answer):
  The panel occasionally resets on its own = NORMAL, Windows sees it too. The difference is RECOVERY:
    Windows: re-queries panel feature config -> rebuilds exact mode mask -> atomically commits ->
             gates stream on completion event -> verifies -> resumes. Result: clean, one-shot.
    Ours:    replays FIXED handshake bytes -> resumes streaming immediately, ungated, unverified.
             Result: panel comes back in a mode that is CLOSE BUT NOT EXACTLY what it currently wants
             (fixed bytes vs live-derived), and we drive it before it's confirmed ready. It streams
             ~300ms, the mismatch/ungated-resume trips the watchdog, we recover the same imperfect
             way again -> CASCADE.

  This single explanation is consistent with EVERY disproof + measurement from this session:
    host path clean (ring empty, controller active, power stable, completion correct),
    init sequence identical to a stable cold boot (so cold boot works),
    recovery latency fixed ~1050ms and "succeeds",
    panel resets ~300ms after each clean recovery,
    cascade under sustained touch.
  Cold boot is stable because after a full HW power/reset the fixed handshake happens to match the
  panel's default post-reset feature state. Recovery (no HW reset) hits a panel whose live feature
  state may differ, so the fixed handshake is not an exact match -> unstable session.

### THE FIX DIRECTION (matches Windows, respects manufacturer design; still requires confirmation)
  Recovery should mirror Windows' SOFTWARE recovery, specifically:
   (a) RE-QUERY the panel's feature/capability config during recovery (GET_FEATURE) and re-derive the
       mode from what the panel currently reports, instead of blindly replaying g6ts_mode_enable /
       g6ts_mode_handshake fixed bytes;
   (b) GATE resumption of input/streaming until recovery is verified complete (don't re-enable the
       IRQ stream the instant reinit returns);
   (c) VERIFY the panel reached stable state before declaring success.
  NOTE: our reinit DOES do a GET_FEATURE 0x70 (stage 5) before SET_FEATURE 0x70 — so check whether we
  ACT on that GET_FEATURE result or ignore it and write fixed bytes regardless. If we ignore it, (a)
  is precisely the gap. This is the next thing to read in g6ts_biosref.c.

### NEXT (non-destructive)
  1. Read g6ts_full_reinitialize_locked stage-5 GET_FEATURE 0x70 handling: do we parse/use the panel's
     returned feature bytes, or discard them and write the fixed g6ts_mode_enable regardless?
     If discarded -> that is the concrete bug to fix (match Windows' RtlQueryFeatureConfiguration-driven
     re-derivation).
  2. Read FUN_1400066c0 + FUN_140006b98 (class-3 apply steps) to capture any final re-arm Windows does
     that we omit.
  3. Only then propose a reversible, branch-based code change for geoca's approval.

### STATUS: Root cause well-supported and now CONSISTENT WITH WINDOWS DESIGN (software recovery, not
   HW reset). Gap = fixed-handshake-replay + ungated/unverified resume vs Windows'
   live-feature-re-derivation + gated/verified recovery. NOTHING changed in tree or on device.
