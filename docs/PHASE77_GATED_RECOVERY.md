# Phase 77 gated device-reset recovery

Phase 77 is an isolated recovery experiment on top of Phase 76. It does not
change QSPI/GPI-DMA transport, the Phase 72 mode exchange, Heat decoding,
contact geometry, tracking, or the saved Phase 75 production entry.

## Observation that motivates the experiment

Two consecutive boots of the same Phase 76 image behaved differently:

- the bad boot initialized at 3.930 seconds, received its first panel
  `RESET_RESPONSE` at 10.507 seconds, and reached 22 reset notifications;
- the resets formed clusters from 10.507 through 40.624 seconds, at 236.884
  and 240.399 seconds, and from 353.624 through 400.701 seconds;
- every recovery completed the existing seven-stage sequence successfully;
- the next identical boot initialized at 4.083 seconds and processed at least
  23,505 Heat frames with zero Heat errors, resets, or recovery failures.

The first reset preceded the bad boot's successful login at 21.680 seconds.
Early password entry therefore is not a sufficient cause. A GNOME Shell crash
also occurred during the clean zero-reset boot, separating the compositor
failure from the panel-reset cascade.

## Concrete driver discrepancy

The Phase 75/76 IRQ path consumes the panel-originated `RESET_RESPONSE`, waits
100 ms, and then unconditionally performs another complete ACPI/GPIO power
cycle. It declares recovery successful after the report `0x56` response and
reopens input without first observing a valid Heat frame.

Recovered Windows evidence distinguishes cold initialization from device-reset
recovery. It does not prove every internal Windows state transition, so Phase
77 deliberately avoids claiming byte-for-byte Windows parity. It tests only
the directly observable lifecycle difference.

## Phase 77 path

The read-only module parameter

```text
mshw0485_touch.reset_recovery_v2=1
```

enables the following behavior:

1. Cold startup keeps the existing hardware power/reset sequence.
2. A panel-originated reset releases every Linux contact and gates input.
3. Because the reset response has already been consumed, recovery begins with
   device and report descriptor enumeration without another power cycle.
4. The unchanged Phase 75 mode sequence is replayed.
5. The IRQ response path opens after the report `0x56` handshake, while every
   non-Heat input report remains gated. The first report `0x12` Heat frame is
   parsed by the normal structural decoder before it can emit Linux input.
6. If software recovery fails, one bounded retry uses the existing full
   hardware initialization path. Existing fatal-transport and retry limits
   remain in force.

This experiment does not emit cold-boot-only report `0x65`, does not invent the
unknown Windows report `0x09` tail, and does not alter the empirically validated
Phase 72 `01 02` / short-`0x09` exchange.

## Diagnostics

`behavior_stats` adds:

```text
hardware_recovery_attempts
software_recovery_attempts
software_recovery_fallbacks
ready_heat_frames
ready_verification_failures
awaiting_ready_heat
```

Successful and failed initialization messages identify `path=hardware` or
`path=software`. These counters make the result distinguish among a clean
software recovery, fallback success, readiness failure, and another delayed
panel reset. An unexpected reset consumed while waiting for any descriptor,
or feature response is counted and terminates that attempt;
it is never silently treated as stale input.

## First-boot correction

The first Phase 77 hardware boot reached the report `0x56` response on all
three cold-start attempts but timed out at the original synchronous Heat gate.
Touching the glass then increased the GPIO51 interrupt count while input was
still gated. This proves that Heat is demand-driven on this panel: requiring a
Heat frame before opening the response path creates a driver deadlock rather
than detecting a panel failure.

The corrected gate does not use a readiness timeout. It opens only the IRQ
response path after the mode handshake, ignores non-Heat data while readiness
is pending, and admits the first Heat frame only after the ordinary complete
Heat parser accepts it. Malformed first frames remain gated and increment
`ready_verification_failures`.

## Offline validation

- 133 parser, classifier, tracking, lifecycle, output-policy, and source
  invariant tests pass;
- the complete client/controller/GPI set builds without warnings using GCC 15
  against the exact `7.1.3-sp11-baseline1+` build tree;
- Sparse reports no findings for all three modules;
- strict kernel style review reports zero errors, warnings, or checks;
- deployment and GRUB scripts pass shell/static validation; and
- the corrected Phase 77 client source version is
  `E61E066E59C2C910A9D7702`.

The corrected client was also reloaded on the first Phase 77 hardware boot. It
completed cold initialization on its first attempt, accepted its first valid
Heat frame on touch, processed at least 694 Heat frames, and recorded zero
Heat errors, resets, readiness failures, or recovery failures during the
initial test window.

The rebuilt isolated initramfs was then cold-booted, independently confirming
that the correction was embedded rather than supplied by the live reload. The
client source version was `E61E066E59C2C910A9D7702`; hardware initialization
completed on its first attempt at 21:19:58, and the first touch admitted a
valid Heat frame at 21:20:03. At 123.90 seconds uptime it had processed 1,408
Heat frames and 784 accepted contact observations with zero Heat errors,
panel resets, readiness failures, or recovery failures. The saved GRUB entry
remained Phase 75 after the one-shot Phase 77 boot.

The optional Clang cross-build cannot be used with this configured kernel
tree because its saved GCC build flags include options unsupported by the
installed Clang 21 driver. The failure occurs before source compilation; the
deployment therefore uses the kernel-matching GCC toolchain.

## Isolation and rollback

The dedicated GRUB entry is `sp11-phase77-recovery`. It enables both the
already-built Phase 76 behavior profile and Phase 77 recovery profile. The
saved default remains `sp11-phase75-identity`; deployment arms Phase 77 for one
boot only. Phase 75 and Phase 76 assets are never overwritten.

Phase 77 must remain local until the following hardware facts are observed:

- cold initialization reaches a valid Heat frame;
- ordinary and multi-touch behavior remains intact;
- at least one real panel reset either recovers through the software path or
  records a precise fallback/failure result;
- no regression appears in a reasonable soak interval.
