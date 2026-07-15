# Phase 60 shape-classifier boundary

This note records the next proprietary stage recovered after the exact Phase
59 NSR gate. It is deliberately documentation-only: the available evidence is
enough to describe the classifier architecture, but not enough to label and
validate every output class safely on Linux.

## Confirmed call path

```text
FUN_180046b10              detector/tracker pipeline
  FUN_180041fd8            candidate geometry and covariance features
  FUN_180040f58            construct ten-feature vector
    FUN_1800406a8          four profile-specific statistical scores
    FUN_180049638          range and state-dependent score overrides
  FUN_1800453e8            candidate-to-track assignment
  FUN_180043b10            temporal class/state processing
```

`FUN_180041fd8` derives a two-dimensional covariance matrix, solves its two
eigenvalues, and writes two confirmed geometry features into each 0xb4-byte
candidate record:

- candidate `+0x8c`: ratio of the major and minor covariance axes, with
  minimum and degenerate-axis handling;
- candidate `+0x90`: a normalized total-spread measure.

The same function also stores the original candidate point count. A secondary
detector is then rerun at three project thresholds. Each rerun contributes its
accepted connected-component count and the largest accepted component's pixel
count.

## Four-score model

`FUN_180040f58` assembles ten floating-point features from the candidate:

- original candidate point count (`+0x9e`);
- largest component pixel count at threshold 0 (`+0x99`);
- largest component pixel count at threshold 1 (`+0x9b`);
- largest component pixel count at threshold 2 (`+0x9d`);
- accepted component count at threshold 0 (`+0x98`);
- accepted component count at threshold 1 (`+0x9a`);
- accepted component count at threshold 2 (`+0x9c`);
- covariance-axis ratio (`+0x8c`);
- normalized spread (`+0x90`);
- surrounding/halo energy ratio (`+0x94`).

`FUN_180048838` supplies the six threshold-rerun fields through
`FUN_180045d98`. `FUN_180040438` computes the signal-weighted covariance.
`FUN_1800432a0` and `FUN_1800434d8` supply the surrounding-energy statistic.
The two covariance-derived values are now emitted by the offline Python tracer.
The DLL scales each square-root eigenvalue by `4.618800163269043`, clamps each
axis to at least 1, and takes major/minor. Its normalized spread is covariance
trace times `6.2831854820251465`, divided by `point_count - 1`; a candidate
with fewer than two points receives 1.0.

Configuration flags can mask individual features. `FUN_1800406a8` then
evaluates four project-profile model blocks. For each enabled block it:

1. subtracts a ten-value profile mean;
2. multiplies the residual through a profile triangular transform;
3. sums the ten squared transformed values;
4. combines half that distance with profile bias/threshold values and a
   runtime offset.

The four scores are stored at candidate `+0xa0`, `+0xa4`, `+0xa8`, and
`+0xac`. In the selected classifier subsection, the four model blocks begin at
subsection `+0x134` with stride `0x1d0`; their means are at block
`+0x198` and additional score constants are at block `+0x190`, `+0x1c0`, and
`+0x1c4`.

This is a four-class statistical model, not a single aspect-ratio palm cutoff.
`FUN_180049638` subsequently applies subsection range tables at `+0x888`,
`+0x8a0`, and `+0x8b8`, plus candidate-state overrides. The resulting scores
feed temporal class logic rather than immediately deleting every non-finger
candidate.

## PSDB and classifier-subsection boundary

The static object selected for project 0x0c83 at `0x180829f90` begins with
`PSDB`, version 4, and project ID 0x0c83. It is one of 23 project blobs spaced
0x9d40 bytes apart; its recorded serialized length is 0x9d3b.

No heap deserialization is required for this classifier. `FUN_18005d660`
selects the PSDB backing object, `FUN_18005daa8` validates its variable records,
and `FUN_18008d2d8` passes **PSDB `+0xdd0`** to `FUN_18004a918`. That pointer is
stored at detector-state `+0x16818`, so all classifier offsets above are
relative to PSDB `+0xdd0`, not to the PSDB header. Reading them from the header
base was the source of the earlier invalid values.

At the corrected base, all four transforms, means, biases, decision constants,
feature masks, and point-count limits are finite and internally consistent.
`tools/extract_windows_classifier.py` performs this bounded extraction without
placing the Microsoft DLL or extracted matrices in the repository.

## Why it is not in the kernel yet

The ten feature meanings, score architecture, and project-0x0c83 model data are
now known, but two proof obligations remain:

- recover the four output-class labels and their temporal transition rules;
- validate those labels against synchronized fingertip, palm, edge-grip, and
  merged-finger frames.

Porting only the covariance ratio or choosing the largest score without those
facts could turn a faithful multi-class pipeline into an unsafe finger
rejection heuristic. Phase 59's NSR gate was suitable for immediate use because
its complete input, mapping, comparison, and corpus behavior were all proven;
this later stage has not reached that standard.

The next safe implementation milestone is to complete the three secondary
detector passes and halo-energy feature in the offline tracer, then feed those
ten values into the extracted scorer for labelled captures. No live filtering
should be enabled until that tracer agrees with Windows class transitions.
