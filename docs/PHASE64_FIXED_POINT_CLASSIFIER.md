# Phase 64 fixed-point shape classifier

Phase 64 completes the project-0x0c83 ten-feature classifier path used by the
finger-only Linux client. It preserves the Phase 63 transport, assignment,
sticky confirmation, and rollback entries.

## Recovered feature pipeline

Direct ARM64 analysis establishes the missing candidate-local operations:

- `FUN_180048838` reruns each sufficiently strong candidate at peak-relative
  fractions 0.5, 0.75, and 0.875;
- each rerun records its admitted island count and largest island size;
- candidates below signal 0.07 retain the default one-island/original-size
  values rather than producing zeroes;
- `FUN_1800432a0` and `FUN_1800434d8` build a bounded 16 by 16 scratch tile,
  exclude other primary candidates, and follow two outward four-connected
  rings whose energy must fall while retaining at least a 0.1499 ratio;
- the resulting halo energy is divided by candidate peak signal;
- `FUN_1800489a0` identifies a separate physical-edge case. The captured
  corpus does not exercise that runtime-calibration-dependent margin, so the
  normal non-edge halo branch is used pending a labelled edge capture.

Together with the already recovered point count, covariance-axis ratio, and
normalized spread, these operations provide all ten inputs to
`FUN_1800406a8`.

## Kernel representation

Linux kernel code must not use the floating-point unit. The profile is
therefore represented in signed Q20.12 fixed point:

1. feature values and profile means are Q20.12;
2. the upper-triangular transforms are Q20.12;
3. transformed residuals remain Q20.12 in 64-bit accumulators;
4. squared distance and class scores use Q40.24;
5. the runtime score offset common to all four classes is omitted because it
   cannot change the winning class.

`tools/generate_classifier_header.py` reproducibly generates the bounded
project profile from an operator-supplied DLL. The DLL is not stored in the
repository. The generated numeric profile is configuration data consumed by
independently written GPL code.

Windows' final output predicate admits classifier values zero and two and
suppresses one, three, five, and six. The four statistical model outputs are
zero through three. Linux therefore allows zero and two to build tentative
track evidence. A confirmed track remains confirmed across an anomalous
frame, matching Windows' temporal intent and preventing visible flicker.

## Offline validation

The 1,381-frame Windows corpus contains 1,113 known one-contact frames. With
the recovered feature generators, the floating-point scorer produces:

```text
class 0: 1106
class 1:    0
class 2:    6
class 3:    1
```

Classes zero and two are output-allowed. The one class-three frame is
transient; Windows' history is specifically designed to prevent one frame
from deleting an established contact.

The Q20.12 scorer preserves the floating-point winning class on all 1,113
contacts. A second regression using the kernel's quantized signal, covariance,
axis, and spread arithmetic also produces zero class mismatches. All 33 unit
tests pass, both client and generated profile pass checkpatch with zero
warnings, and the matched 7.1.1 module builds with `W=1`.

## Live validation

The isolated entry was booted on the target Surface with command-line marker
`sp11_entry=7.1.1-phase64`. Sysfs reported the expected live module source
version `C97172EE0D703AF2ED13B54`; the older root-filesystem module did not
replace the copy loaded from the dedicated initramfs.

A mixed one-, two-, and three-finger exercise produced 1,790 input reports,
23 contact-down transitions, and a maximum of three simultaneous contacts.
The classifier evaluated 2,885 candidates:

```text
class 0, allowed: 2862
class 1, denied:     1
class 2, allowed:   20
class 3, denied:     2
```

No touchscreen transport recovery, timeout, abort, kernel error, or crash was
recorded. A separate 31-second hands-off capture produced zero input reports,
zero contact transitions, and zero active slots. Dynamic classifier logging
was disabled again after the capture.

## Safety boundary

This classifier never sends commands to the panel and cannot alter firmware.
It consumes only the already decoded Heat frame. Pen-driven rejection remains
out of scope. Broad size/span rejection remains ahead of the statistical
classifier as a fail-safe. The Phase 63 and safe 7.1.3 boot entries are not
modified.

## Isolated deployment checkpoint

The matched module was built for `7.1.1-sp11-gpicmp1+` and embedded in a new
initramfs. The installed root-filesystem module was then restored to the live
Phase 63 version, so only the dedicated GRUB entry selects Phase 64.

```text
entry id: sp11-phase64
command-line marker: sp11_entry=7.1.1-phase64
Phase 64 module source version: C97172EE0D703AF2ED13B54
installed/live Phase 63 source version: 2720A95296AB755A5FD2695

d00a501487c8b647c43674f3e1bef63863b40a2df043df820084a6419ec1e8d6  initrd.img-7.1.1-sp11-gpicmp1+-phase64
fcefdc928b6e45a8212722c9132b9da2dc1c197fc4890f7a9bab3c31d1584b94  sp11-7.1.1-phase64-hybrid.dtb
6f263da75052c54b16d9be21b315beab6b45a2c27c08710d5362b033b4aebf30  vmlinuz-7.1.1-sp11-gpicmp1+
```

The Phase 63 initramfs remains unchanged at
`db4f93a0e044178eb0bb293249a978731e5d06ee0e7504e591e602dbc5b62480`.
The saved 7.1.3 default remains unchanged. GRUB is armed to select Phase 64
once on the next reboot and then return to the saved baseline automatically.
