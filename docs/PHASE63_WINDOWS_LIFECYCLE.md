# Phase 63 Windows-informed lifecycle gate

Phase 63 addresses a live failure in which one physical finger occasionally
produced a brief second Linux contact. A read-only `/dev/input/event1` trace
proved that the second contact received a new tracking ID: it was a transient
second Heat candidate, not a stale multitouch slot left pressed by Linux.

## Recovered Windows behavior

Direct analysis of `TouchPenProcessor0C83.dll` confirms that Windows does not
copy every accepted Heat component into a touch report. Its pipeline computes
ten shape/noise features, evaluates four statistical scores, globally assigns
candidates to persistent tracks, retains a ten-entry class history, advances a
five-state lifecycle, and then applies a separate finger-output gate.

The project-0x0c83 transition table uses different minimum histories for each
old/new class pair:

```text
0, 5, 2, 1
8, 0, 4, 30
2, 5, 0, 4
1, 5, 3, 0
```

Windows telemetry also has reporting-delay bins for 2-5, 6-10, 11-50,
51-100, and 101-or-more processing cycles. Variable classification latency is
therefore an intentional part of the Windows design rather than an accidental
transport delay.

The four class labels and several context overrides remain unproven. The
repository consequently does not embed Microsoft model matrices or pretend
that a Linux heuristic is an exact class mapping.

## Linux implementation

The independently written Linux lifecycle uses only observable component and
track properties:

- normal new candidates confirm after three consecutive observed frames;
- one- or two-cell candidates require five frames;
- a new candidate within 2,048 logical units of an established finger requires
  at least five frames;
- a nearby candidate no more than half the established finger's strength or
  pixel count requires eight frames;
- tentative and coasting tracks remain available for global reassociation but
  are never sent to the input subsystem;
- confirmation is sticky until track closure, so shape jitter cannot make a
  real finger flicker.

Close real multitouch is delayed rather than deleted. A sustained nearby
second finger will therefore appear after its evidence window.

## Validation

The Python reference and kernel implementation share the policy constants.
Deterministic tests cover global assignment, crossing fingers, dropout
reassociation, stale-contact suppression, stationary smoothing, a two-frame
transient, a sustained nearby weak candidate, a distant real second finger,
and confirmed-track shape jitter.

```text
29/29 unit tests passed
checkpatch: 0 errors, 0 warnings, 0 checks
kernel vermagic: 7.1.1-sp11-gpicmp1+ SMP preempt mod_unload modversions aarch64
module source version: 2720A95296AB755A5FD2695
```

The complete 1,381-frame Windows corpus still decodes without errors. It has
20 single-finger onsets; the lifecycle reports each after exactly three input
frames and does not manufacture any second contact:

```text
raw contact frames:      1113
reported contact frames: 1073
idle frames:              268
onsets:                     20
onset delay:          3 frames for all 20
```

The client-only module was hot-loaded on the experimental kernel on
2026-07-15. Built, installed, and live source versions matched. The GENI
controller and GPI DMA modules remained loaded and unchanged. The rollback
copy is under:

```text
/var/backups/sp11-touchscreen/windows-lifecycle-20260715-100619
```

The repeated live input capture contained 1,318 reported frames and 52 contact
births. Repeated one-finger taps reported one contact, the multitouch portion
reached three simultaneous contacts, and only one reported contact had a
lifetime of two frames or less. The operator observed no ghost press during
the test. This is a short hardware validation, not a substitute for a longer
labelled raw-Heat capture; the three-contact periods must not be classified as
expected or unexpected without a synchronized record of the physical gesture.

## Isolated boot checkpoint

The existing Phase 62 and safe 7.1.3 entries remain unchanged. Phase 63 has a
dedicated GRUB entry, kernel/DTB directory, and initramfs:

```text
entry id: sp11-phase63
command-line marker: sp11_entry=7.1.1-phase63
initramfs module source version: 2720A95296AB755A5FD2695

db4f93a0e044178eb0bb293249a978731e5d06ee0e7504e591e602dbc5b62480  initrd.img-7.1.1-sp11-gpicmp1+-phase63
fcefdc928b6e45a8212722c9132b9da2dc1c197fc4890f7a9bab3c31d1584b94  sp11-7.1.1-phase63-hybrid.dtb
6f263da75052c54b16d9be21b315beab6b45a2c27c08710d5362b033b4aebf30  vmlinuz-7.1.1-sp11-gpicmp1+
```

The embedded, installed, and live client source versions match. The preserved
Phase 62 initramfs still hashes to
`976e8218d30d23834c592508d9c65bf84f2868eff9daa69e8c9929292e136c41`.
