# Phase 76 low-latency behavior experiment

Phase 76 is an isolated contact-processing experiment on top of the
hardware-validated Phase 75 DMA baseline. It does not change QSPI/GPI-DMA,
panel power, feature reports, reset recovery, the device tree, or the driver
identity. The Phase 75 boot image remains the saved fallback.

## Motivation

Phase 75 combines the recovered classifier with a Linux-fitted 4096-unit
assignment gate, coordinate smoothing, and a three-frame normal-contact
admission window. Later static analysis established three narrower facts:

- the project profile scales sensor centroids independently on X and Y and
  uses a strict radius-five assignment gate;
- `FUN_18004a330` stores the chosen contact X/Y directly; its blend applies to
  a different scalar, not the output coordinates;
- `FUN_180047078` computes a distinct final-output centroid after detection.

The earlier Phase 65 experiment also hardware-tested two-frame admission for
strong contacts. A later recovery experiment unintentionally restored the
three-frame value; that reversion was unrelated to contact processing.

## Gated behavior

The read-only `mshw0485_touch.behavior_v2=1` parameter enables four changes as
one explicitly labelled experimental profile:

1. project-0x0c83 sensor-space assignment scales and strict radius five;
2. direct final coordinates without the Phase 75 fitted smoothing bands;
3. the ordinary zero-context output-centroid branch using baseline index 171,
   while retaining the detector centroid for assignment;
4. two-frame admission for strong contacts.

Weak contacts retain five-frame admission and nearby split candidates retain
their longer gate. The profile is mutually exclusive with the incomplete
`windows_orchestrator` experiment. It deliberately does not enable the
unproven lifecycle branches or score postprocessing from that profile.

This is not a claim of complete TouchPenProcessor parity. The alternate
profile-region, provider-context, special-state, merged-output, and
split-output branches require live inputs that have not been established in
the raw Heat stream.

## Diagnostics

The driver exposes a read-only `behavior_stats` file on the bound SPI device,
normally:

```text
/sys/bus/spi/devices/spi0.0/behavior_stats
```

It reports the active profile, decoded Heat frames and errors, component and
contact counts, rejection reasons, assignment/new-track counts, Linux output
counts, processing time, panel resets, and recovery results. These counters
let a hardware run distinguish latency or contact-policy problems from panel
transport failures without enabling a write-capable laboratory interface.

## Offline validation

- all 131 parser, classifier, tracking, lifecycle, output-policy, and source
  invariant tests pass;
- the matched client, GENI controller, and GPI modules build without warnings
  against the exact `7.1.3-sp11-baseline1+` tree;
- strict kernel style review and Sparse analysis report no findings;
- all 1,381 captured Windows Heat frames decode, with zero fixed-point class
  or assignment mismatches across 1,113 accepted contacts;
- the integer Phase 76 centroid matches the recovered float32 expanded-
  centroid oracle for all 1,113 corpus contacts; and
- relative to the Phase 75 detector centroid, the new output point moves by a
  mean 13.270 X / 18.184 Y logical units and a maximum 115.875 X / 198.477 Y
  units on the 0..32767 axes.

## Safety and deployment

`scripts/deploy_phase76_behavior.sh` builds a separate Phase 76 initramfs,
verifies the exact client/controller/GPI module set, installs a separate GRUB
entry, and selects it for the next boot only. It copies the already validated
Phase 75 kernel and device tree and leaves the Phase 75 image, saved GRUB
default, and root-filesystem module set unchanged.

The current Windows corpus is valuable for parser and fixed-point regression,
but it is dominated by single-contact frames and does not prove physical-edge,
palm, close multi-contact crossing, or fast keyboard behavior. Promotion can
therefore occur only after direct hardware validation; until then Phase 75 is
the production baseline.
