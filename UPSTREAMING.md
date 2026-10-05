# Linux touchscreen upstreaming workflow

The repository contains production baselines, historical phases, boot assets,
analysis tooling, and modified kernel components.  Those are valuable for
reproduction, but the upstream submission should be reduced to a clean patch
series against current Linux.

## 1. Re-check current upstream

Confirm the current state of HID-over-SPI, Qualcomm GENI SPI, GPI DMA, DT
bindings, and any relevant Surface/ARM64 support before preparing patches.
Avoid carrying compatibility code that upstream no longer needs.

## 2. Identify the minimal accepted delta

Start from the hardware-validated behavior, then reproduce only the required
changes against a clean upstream base.  Do not submit complete historical phase
snapshots simply because they were useful during bring-up.

Separate:

- generic HID/SPI/GENI/GPI changes, if genuinely required;
- the touchscreen client/transport support;
- device-tree/binding changes;
- optional cleanup or diagnostics.

Each should be independently reviewable where practical.

## 3. Preserve licenses and provenance

The existing SPDX expression of each target kernel file controls.  Preserve
original copyright notices and authorship.  See `LICENSING.md`.

Do not change an imported GPL/BSD expression to a repository-wide license, and
do not manufacture another contributor's `Signed-off-by:` or
`Co-developed-by:` trailer.

## 4. Remove laboratory-only surfaces

Before submission, remove temporary debug controls, one-shot boot mechanics,
raw laboratory command interfaces, verbose tracing, and rejected experimental
branches unless a maintainer specifically asks for them.

Keep the final driver bounded, reviewable, and based on standard kernel
interfaces.

## 5. Validate

At minimum, as applicable:

```bash
./scripts/checkpatch.pl --strict <patches>
./scripts/get_maintainer.pl <patches>
```

Build the affected architecture/configuration and modified subsystems.  Run
relevant DT schema checks.  Hardware-test cold boot, touch enumeration,
single/multi-touch, edges, rapid typing/tapping, recovery behavior, and
suspend/resume if the series changes power management.

## 6. DCO and submission

Each contributor in the submission path supplies their own DCO sign-off.  Use
`git commit -s` for commits you are entitled to certify.

Generate patches with `git format-patch`; use current
`scripts/get_maintainer.pl` output and normal kernel mailing-list workflow.

Linux submission guidance:
https://docs.kernel.org/process/submitting-patches.html

## 7. Keep the research tree as evidence, not a dependency

The phase history, Windows-oracle analysis, hashes, and hardware results can
support the explanation of why the patch is correct.  The submitted Linux code
must not depend on proprietary artifacts or on this repository being present.
