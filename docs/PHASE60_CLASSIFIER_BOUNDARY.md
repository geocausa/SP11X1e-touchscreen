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

The same function also stores the candidate point count and six byte-sized
extent/sample descriptors used by the next stage.

## Four-score model

`FUN_180040f58` assembles ten floating-point features from the candidate:

- point count;
- six byte-sized geometry/sample fields;
- axis ratio;
- normalized spread;
- one additional floating-point candidate statistic whose final meaning is
  not yet named.

Configuration flags can mask individual features. `FUN_1800406a8` then
evaluates four project-profile model blocks. For each enabled block it:

1. subtracts a ten-value profile mean;
2. multiplies the residual through a profile triangular transform;
3. sums the ten squared transformed values;
4. combines half that distance with profile bias/threshold values and a
   runtime offset.

The four scores are stored at candidate `+0xa0`, `+0xa4`, `+0xa8`, and
`+0xac`. In the project-0x0c83 profile, the four model blocks begin at profile
`+0x134` with stride `0x1d0`; their means are at block `+0x198` and additional
score constants are at block `+0x190`, `+0x1c0`, and `+0x1c4`.

This is a four-class statistical model, not a single aspect-ratio palm cutoff.
`FUN_180049638` subsequently applies profile range tables at `+0x888`,
`+0x8a0`, and `+0x8b8`, plus candidate-state overrides. The resulting scores
feed temporal class logic rather than immediately deleting every non-finger
candidate.

## Why it is not in the kernel yet

The embedded project-0x0c83 matrices and constants can be extracted exactly,
but three proof obligations remain:

- name the tenth feature and verify the six byte-field semantics;
- recover the four output-class labels and their temporal transition rules;
- validate those labels against synchronized fingertip, palm, edge-grip, and
  merged-finger frames.

Porting only the covariance ratio or choosing the largest score without those
facts could turn a faithful multi-class pipeline into an unsafe finger
rejection heuristic. Phase 59's NSR gate was suitable for immediate use because
its complete input, mapping, comparison, and corpus behavior were all proven;
this later stage has not reached that standard.

The next safe implementation milestone is an offline score tracer that emits
all ten features and four scores for labelled captures. No live filtering
should be enabled until that tracer agrees with Windows class transitions.
