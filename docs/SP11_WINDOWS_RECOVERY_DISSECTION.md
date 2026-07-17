
=====================================================================================
UPDATE 2026-07-16 (pm) — Byte-exact 0x09 status + Windows partition mounted + decision point
=====================================================================================

SOURCES NOW AVAILABLE (all mounted read-only this session):
  - Windows C: /dev/nvme0n1p3 -> /mnt/win  (DriverStore has hidspi_km.inf, TouchPenProcessor0C83.dll
    + 0C80 variant; INFs contain NO mode-config bytes — mode is built at runtime in the DLL/sys).
  - USB clone /dev/sda2 -> /mnt/usb : prior-RE archive at /mnt/usb/home/ubi/Documents/SP11/TOUCHSCREEN
    (firmware .mbn, acpi/, mshw048a_enum.reg, Claude_soruce_of_truth/, touchwork/, Research_Hub).
    No text file found decoding the 0x09 report or the 0x70/0x56 origin (searched).

### 0x09 OUTPUT_REPORT — BYTE-EXACT STATUS (content_len = 63)
  Dump was db L40 = 64 bytes from packet base; packet = 4(SPI hdr)+4(HID hdr)+63(content)+1(pad)=72.
  So the 64-byte dump shows content bytes [0x00..0x37] = 56 of 63 bytes. LAST 7 bytes [0x38..0x3e]
  fell outside the dump window and are NOT captured.

  VARIANT A (content, offset from content start):
    0x00: 8e a1 01 00 90 01
    0x06..0x27: 00 (all zero)
    0x28: 14 03
    0x2a..0x37: 00 (all zero, visible)
    0x38..0x3e: *** UNKNOWN (7 bytes, not in dump) — surrounding region is zeros, likely 00 but
                 NOT CONFIRMED ***
  VARIANT B (content):
    0x00: 8e a5 00 02
    0x04..0x26: 00
    0x27: 14 03            (note: B's 14 03 is one byte earlier than A's, due to fewer leading params)
    ...  40 appears ~0x2e
    0x38..0x3e: *** UNKNOWN (same gap) ***

  Repeated 8e a1.. seen at later eb00 READ commands (lines 6500/6559) = STALE buffer reuse at the
  same address 79071100, NOT new data. Confirms buffer content, adds no new bytes.

### HONEST BLOCKER for building the fix:
  We have 56/63 bytes exact. The 7 trailing bytes are almost certainly zero (region is zeros) but
  unconfirmed. Building a deploy on "likely zero" violates the "be 100% sure / don't get busted"
  bar. Two ways to close it:

  CLEAN (recommended): boot Windows (present on nvme0n1p3) and RE-RUN the KDNET capture with
    db @x4 L48 (72 bytes) to get the FULL 0x09 report, AND trigger a panel reset to capture an
    actual RECOVERY event (never captured before) to confirm Windows re-sends 0x09 on recovery.
    => yields the complete, wire-validated sequence with zero guessing.
  BOUNDED-RISK: build the branch with 56 known bytes + 7 assumed-zero, clearly documented, on an
    isolated GRUB entry. Reversible. If the panel rejects it, the tail bytes are implicated.

### CRITICAL SEQUENCING NOTE (do this FIRST, before either option — 5 min, no code, no risk):
  COLD-BOOT ENDURANCE TEST. Boot known-good phase68 COLD (no recovery), sustained touch several
  minutes, count panel resets.
    - Cold boot uses the SAME 0x70/0x56 mode-setup as recovery.
    - If cold boot is LONG-TERM STABLE -> 0x70/0x56 mode-setup is ADEQUATE; the bug is
      RECOVERY-MECHANICS (D1 hw re-cycle desync / D3 ungated resume). The 0x09 rewrite would be
      hardening, NOT the fix. Building the 0x09 branch first would waste a cycle.
    - If cold boot ALSO resets frequently -> 0x70/0x56 mode-setup is INADEQUATE; the 0x09 path is
      the core fix and is worth the Windows re-capture.
  THIS TEST DECIDES WHICH BUG WE ARE FIXING. It gates everything else.

### DECISION POINT (for geoca):
  Recommended order:
    1. Cold-boot endurance test (5 min, no code) -> tells us mode-setup vs recovery-mechanics.
    2a. If mode-setup implicated: boot Windows, re-capture full 0x09 (L48) + a recovery event ->
        then build the Windows-method branch with byte-exact data.
    2b. If recovery-mechanics implicated: build a branch that adds a readiness GATE + makes recovery
        software-only (drop the redundant hw power-cycle), leaving mode-setup as-is.
    3. Either branch: isolated GRUB entry + git branch, known-good phase68 untouched (phase70/71
       isolation pattern). Log results. Push concrete facts to repo.

  Two-bugs framing (geoca's, likely correct):
    BUG #1: panel resets too often in the first place (may be inherent/expected at SOME rate).
    BUG #2: our recovery makes it WORSE ("swarming"/cascade) vs Windows' clean one-shot recovery.
  The cold-boot test separates these: baseline reset rate at cold boot = BUG#1 magnitude; the
  cascade-above-baseline after a reset = BUG#2.

NOTHING changed in tree or on device. Windows + USB mounted READ-ONLY.
