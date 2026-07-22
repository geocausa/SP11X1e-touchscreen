# Phase 86: Windows chronology into Heat

Phase 86 is the first isolated end-to-end laboratory entry. It preserves
Phase 84 and Phase 85 as input-disabled diagnostic checkpoints, but continues
the same evidence-gated cold chronology into the normal Linux Heat consumer.
The saved GRUB default remains the hardware-validated Phase 75 baseline.

The usual reductionist order would run Phase 84 and Phase 85 first. For this
hardware trial, the operator explicitly selected the combined entry because
leaving an activated Heat collection unconsumed may itself create a panel
state unlike steady Windows operation. The tradeoff is understood: a failure
before `wait-heat` still localizes the exact initialization stage, but a clean
combined boot does not independently prove each earlier stop checkpoint.

## Admission boundary

`parity_heat_input=1` is accepted only together with
`windows_init_parity=1` and `parity_cfu_inventory=1`. Input remains closed
unless all of the following have succeeded:

1. the recovered Windows power/reset and controller initialization;
2. exact device and report descriptor validation;
3. early report `0x73` and Heat capability report `0x06` validation;
4. provider-built A1/A5 feedback and the captured acknowledgement;
5. exact `SET 0x05`, `GET/SET 0x70`, and `SET 0x56` exchanges;
6. the bounded CFU inventory/no-update branch, with no firmware payload path;
7. the captured final report `0x73` boundary.

The continuation sends no extra mode or vendor command. Report `0x05` has
already activated the Heat collection in the captured Windows order. Phase 86
only enables the IRQ response consumer and keeps input suppressed until the
first complete report `0x12` passes the existing structural Heat parser.

An unexpected CFU result still stops at `windows-cfu-branch-required`; it
never enables input and never sends firmware data.

## Contact processing profile

The entry enables the separately hardware-tested Phase 76 behavior profile:

- project-0x0c83 per-axis sensor-space assignment geometry;
- the recovered normal expanded-output centroid;
- direct output coordinates rather than Phase 75's fitted X/Y smoothing;
- two-frame admission for strong contacts, with longer weak/split gates.

This is closer to the recovered ordinary Windows path than Phase 75, but it is
not claimed to reproduce the complete proprietary TouchPenProcessor pipeline.
The remaining lifecycle/context/output boundary is documented in
`PHASE69_WINDOWS_PROCESSING_PARITY.md`.

## Recovery policy

The entry enables the validated host-fault recovery and ready-line quiesce
safeguards. A panel reset selects the cold hardware path, so the complete
parity sequence is rerun; the unsupported Windows-parity software-reset order
is not selected. Phase 75 remains untouched and is automatically selected on
the boot after this one-shot experiment.

## Expected observable states

Success before physical contact:

```text
initialization_stage=wait-heat
mode_enabled=1
awaiting_ready_heat=1
```

Success after the first valid touch frame:

```text
initialization_stage=wait-heat
mode_enabled=1
awaiting_ready_heat=0
ready_heat_frames=1
```

Any earlier terminal stage identifies the exact owner or response that did
not match the recovered chronology.
