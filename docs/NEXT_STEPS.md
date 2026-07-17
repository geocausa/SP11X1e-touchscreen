# Current lead / next steps (updated 2026-07-17)

Start here when resuming. This file points at the active root-cause lead so no
one re-derives prior work.

## Active root cause (high confidence, live-hardware confirmed)

The frequent panel resets under sustained touch are caused by a TRUNCATED
mode-config payload in `g6ts_full_reinitialize_locked`:

- We send `SET_FEATURE 0x70` (and `0x05`) with `{0x01}`; Windows sends
  `{0x01, <config>}` (6 bytes). We also never emit the `OUTPUT_REPORT 0x09`
  carrying `8e <config>`.
- `<config>` is DERIVED from the `GET_FEATURE 0x70` response, which stage 5
  currently reads and then DISCARDS.
- Report `0x09`, abandoned in phase 66-67 as "unsupported", is in fact supported
  and sent by Windows on every init and recovery. The phase 66 timeout was a
  wrong payload/order, not panel rejection.

Full evidence, wire-exact bytes, exact code targets, and the fix procedure:
**[docs/PHASE72_LIVE_KDNET_ROOT_CAUSE.md](PHASE72_LIVE_KDNET_ROOT_CAUSE.md)**

Supporting working notes:
- docs/SP11_DRIVER_DISCREPANCY_AUDIT.md   (candidate elimination, live traces)
- docs/SP11_WINDOWS_RECOVERY_DISSECTION.md (Windows recovery call chain)

## Immediate next actions (in order, all reversible)

1. Read-only baseline: cold-boot phase68, sustained touch several minutes, count
   resets. Confirms whether cold boot shares the truncated-config reset rate.
2. Implement the derived-config fix (retain GET_FEATURE 0x70 bytes; send
   `SET_FEATURE 0x05/0x70 = {0x01,<config>}`; emit `OUTPUT_REPORT 0x09 =
   {0x8e,<config>}` variants A then B; keep `0x56` unchanged) on a NEW git branch
   and an isolated GRUB entry. Known-good phase68 untouched.
3. Deploy, sustained-touch test, count resets vs baseline, log, push facts.

## If the fix reduces but does not eliminate resets

Address recovery mechanics next (secondary): Windows' device-initiated-reset
recovery is software-only (no HW power-cycle), event-gated (KeSetEvent), and
verified. Ours does a full GPIO/ACPI power-cycle and resumes streaming ungated.
See PHASE72 "Recovery mechanics" section.

## Boundaries respected

No captures committed to the repo (per README scope). Raw KDNET capture kept off-
tree at host `C:\Users\SurfacePro7\Documents\KDNET\sp11_clean_3events.log`.
No code changed yet; known-good phase68 install untouched.
