# SP11 OLED touch production-v1 candidate

This directory preserves the eight-patch touch finalization from kernel commit
`3094f120b90e7b2df9ccb326b1193d66bcc217a5` to
`f3e18f68bc2d6ff621acbbd0f7570417a9e6f718` on the owner's OLED Surface Pro 11.
It provides working finger multitouch on `7.3.0-sp11-unified13` without
`mshw0485_touch.*` command-line parameters or a touch-processing daemon.
**Pen support and full Windows feature parity remain unfinished.** See
[the stack audit](../docs/TOUCH_PEN_PARITY.md).

The `production-v1` name is the driver's profile string. It does not certify
other hardware, other kernels, sustained multi-cycle soak, or pen input.
The existing root build and locked installation recipes retain their historical
sources and recovery behavior. This candidate is a separate client module for
the already qualified unified13 GENI/GPI/DT composition.

## Contents and provenance

- `mshw0485_touch.c`: exact final kernel source, 3,061 lines, GPL-2.0.
- `g6ts_classifier_profile.h`: required classifier header from the same kernel
  tree; byte-identical to the already published `phase55/modules/` header.
- `patches/0001..0008`: original kernel-format patches, preserving authorship,
  messages, and licensing. They apply to the unified13 kernel base above,
  **not** directly to `phase55/modules/` or pristine upstream Linux.
- `evidence/`: Linux stats/logs from the local finalization work and the current
  owner-assisted finger test. No Windows binary, decompilation, private Windows
  capture, firmware payload, or Bluetooth identity is included.
- `SHA256SUMS.txt`: hashes of the source, classifier header, patches and evidence.

The baseline driver is 3,426 lines and its lifecycle header is **253 lines**.
Patch 8 alone deletes 1,655 lines across three files and adds 144; that is not the
net reduction across the complete series. The final source has one read-only
parameter, `pm_sleep_mode`, default `off` (also accepts `sleep` and `legacy`).

## What was actually exercised

| Revision / evidence | Observation | Limit |
| --- | --- | --- |
| Pre-Patch-8 clean profile, `test2b_live_s2idle_pass.txt` | Real s2idle cycle followed by 315 Heat frames and zero resets | Earlier source; not the final Patch 8 image |
| Patch 7, `test3_live_patch7_dsp_pass.txt` | 1,772 Heat frames, 77 merged splits, 293 edge-palm rejections, zero resets | Counters demonstrate exercised paths, not Windows-equivalent accuracy |
| Patch 8, `test4_live_patch8_production_pass.txt` | Zero-argument load, init in 1.059 s, idle and `pm_test=devices`, zero resets | Both snapshots have `heat_frames=0`, `awaiting_ready_heat=1`; no post-resume input demonstrated in that file |
| Patch 8, `test5_patch8_finger_input.txt` | Owner confirmed tap/drag and pinch; 414 Heat frames, 410 output contacts, no Heat/IRQ faults or resets | Runtime input confirmation; no new cold boot or controlled post-resume gesture test |
| Patch 8, `test6_patch8_cold_boot_pass.txt` | Isolated one-shot cold boot (`sp11-touch-final`, zero `mshw0485_touch.*` cmdline args, `srcversion=2CD3A3123ABDF93462D80E7`), init in 1.106 s, 309 cold-boot Heat frames (26.0 us avg), zero resets/errors | Single-unit cold-boot verification; does not cover sustained multi-hour soak or other hardware |
| Patch 8, `test7_patch8_cold_boot_s2idle_pass.txt` | Real full-SoC `s2idle` + power-button wake on the cold-booted Patch 8 image: controller initialized 147.0 ms after `PM: suspend exit`, +1,052 post-wake Heat frames (+977 output contacts, 31.7 us avg), `pm_off_acks=1`, `pm_last_wake_us=0`, zero resets/errors | Single `s2idle` cycle on one unit; repeated-cycle soak and battery-draw measurements remain open |

`pm_last_wake_us=0` is a microsecond-granularity measurement of the synchronous
resume callback. Recovery runs asynchronously. The cold-boot Patch 8 real
`s2idle` log (`test7`) shows controller initialization 147.0 ms after
`PM: suspend exit`, followed by the first valid post-wake Heat frame; actual
input readiness requires that subsequent valid Heat frame. Do not describe this
as instantaneous touch wake. OFF/SLEEP writes have no response by design; the
`pm_off_acks` counter records a successful command write, not an acknowledgment
received from the controller.

The isolated one-shot GRUB trial entry (`sp11-touch-final`) was cold-booted and
verified on November 25 (`test6` and `test7`), with `grubenv` auto-clearing back
to the untouched default baseline. No reboot or boot configuration change is
required to inspect/build this directory.

## Build and verify without installing

Use the exact configured unified13 build tree, including its `Module.symvers`.
The client requires the existing matched GENI/GPI changes and touchscreen DT.
A stock kernel with a matching-looking release string is insufficient.

```sh
make -C production-v1 KDIR=/path/to/configured/unified13/build
python3 -m unittest discover -s tests -p 'test_production_v1*.py' -v
(cd production-v1 && sha256sum -c SHA256SUMS.txt)
```

The Makefile refuses other configured release strings. It builds only the client
and provides no installer, automatic reload, suspend, or reboot action. The
resulting `.ko` is a local build artifact; do not replace installed modules or
mix it with the 7.1.3 controller/GPI set.

Reproduce the kernel series in an isolated unified13 source checkout with
`git am /path/to/production-v1/patches/*.patch`, then compare the resulting source
with this snapshot. Kernel mailing-list submission still requires a focused
rebase, current upstream review, and each contributor's own DCO certification;
these archived patches are not represented as submission-ready.

## Repository validation for this import

On November 24, the imported client built with `W=1` and zero warnings against
`7.3.0-sp11-unified13`; vermagic matches that configured release. All eight
archived patches passed `checkpatch.pl --strict --no-signoff` with zero errors,
warnings or checks. Replaying them against the exact baseline reproduced this
source byte-for-byte (including lifecycle-header deletion and MAINTAINERS).

The repository's 217 offline tests passed, including the seven imported source/
protocol contract checks and twelve synthetic CCP-inspection cases. The seven
contracts include Python reference calculations and source assertions; they do
not execute the driver on hardware. Neither those tests nor a successful module
build demonstrate pen functionality.

To inventory a **local binary report** including its report ID and scan time:

```sh
python3 tools/inspect_pen_ccp.py /private/one-heat-report
# Or supply only the vendor payload, after its seven-byte section header:
python3 tools/inspect_pen_ccp.py --format vendor /private/one-ccp-payload
```

This reads a file and prints JSON; it does not access the controller, change its
mode, upload captures, or emit input events.
