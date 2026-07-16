# Phase 70 kernel frame orchestrator

Phase 70 turns the bounded Phase 69 reverse-engineering result into a
kernel-compilable, opt-in processing profile. It does not alter the proven
QSPI/GPI-DMA transport, the seven-stage panel initialization sequence, reset
recovery, or the default Phase 68 touch policy.

## What is baked into the kernel client

`tools/generate_lifecycle_header.py` reads an operator-supplied
`TouchPenProcessor0C83.dll` and emits a deterministic GPL-2.0 profile header.
The generated header contains no DLL bytes or executable code. It records:

- all 20 old-class/new-class transition records;
- the ten-sample history capacity;
- class-specific component point-count ranges;
- the corrected common classifier score offset;
- the 68-by-46 sensor's recovered per-axis assignment scales; and
- the normal strict assignment radius of five.

The client now retains both logical output coordinates and Q8.24 sensor
centroids. The opt-in path predicts in sensor space, quantizes X and Y with
their separate recovered factors, globally assigns with the existing
Hungarian solver, and rejects equality at the radius-five boundary. Q8.24 was
selected because the source arithmetic is IEEE-754 single precision. Across
all 1,113 accepted contacts in the saved Windows Heat corpus, the fixed-point
kernel quantization produces the same assignment coordinates as the recovered
floating-point oracle.

For matched tracks, the opt-in path stores new X/Y directly and keeps velocity
separately. It does not use the Phase 58 Linux-only exponential coordinate
filter. It retains ten score vectors and evaluates the recovered current-score
then history-score ordering, including the unclassified new-track row and
point-count gate.

The final per-frame Linux event boundary is now explicit:

```text
decode/detect -> global assignment -> matched-track update
              -> unmatched-track lifecycle -> new-track allocation
              -> one final Linux contact collection
```

No `input_sync()` occurs inside an intermediate stage. Retained unmatched
tracks remain available for reassociation but are never emitted as contacts.

## Why it remains opt-in

Load-time parameter `g6ts_biosref.windows_orchestrator=1` selects this profile.
The parameter is read-only and defaults to false, so the running and newly
built default module retains Phase 68 behavior.

The recovered score-three postprocessor depends on candidate producer fields
`+0x4d/+0x4e`. Later state-one-to-state-two/state-four lifecycle branches also
consume provider-owned frame, context, region, and component-scalar values
that are not present in raw Heat reports. Phase 70 does not invent those
inputs. Until they have live intermediate ground truth, the opt-in profile
uses the existing bounded unmatched-track hold and Linux collection boundary
rather than claiming the full private Windows output graph.

This distinction is intentional: the exact geometry and base transition
pieces are compiled and reviewable, while unproven provider values remain
visibly outside the active policy.

## Reproduction and validation

Regenerate or verify the committed profile from a local DLL:

```bash
python3 tools/generate_lifecycle_header.py \
  /path/to/TouchPenProcessor0C83.dll \
  > /tmp/g6ts_lifecycle_profile.h

python3 tools/generate_lifecycle_header.py \
  /path/to/TouchPenProcessor0C83.dll \
  --check phase55/modules/g6ts_lifecycle_profile.h
```

Validation performed for this checkpoint:

- generated header byte-for-byte matches the validated local DLL;
- 1,113/1,113 corpus contacts match the Windows assignment quantization;
- all repository unit and invariant tests pass;
- the complete three-module set builds against
  `7.1.1-sp11-gpicmp1+`; and
- `g6ts_biosref.ko` exposes the opt-in parameter with the expected target
  vermagic.

No Phase 70 module was installed, hot-loaded, added to an initramfs, or made a
GRUB default while creating this checkpoint.
