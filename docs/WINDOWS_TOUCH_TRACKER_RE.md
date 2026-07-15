# Windows touch tracking and post-processing

This note separates behavior recovered from `TouchPenProcessor0C83.dll` from
the numeric policy fitted for the Surface Pro 11 Linux driver.  The DLL was
analysed as ARM64 at image base `0x180000000`.

## Recovered pipeline

The detector continues well beyond candidate creation:

```text
FUN_180046b10
  FUN_180040b58  candidate labelling
  FUN_180041fd8  centroid, covariance/shape and weak-candidate features
  FUN_180040f58  candidate classification/setup
  FUN_1800453e8  candidate-to-track global assignment
  FUN_180043b10  lifecycle transitions
  FUN_180041150  classification and tracking policy
  FUN_1800468c0  project-tuning/output state
  FUN_180049458  output construction
```

An outer TrackLib layer is then called by `FUN_18004ade0`.  Event-name anchors
confirm matching, tracking logic, backward/forward prediction, weak-blob NSR
deletion, and copying a blob into a finger output record.

## Matching facts

`FUN_1800453e8` builds a cost matrix between current candidates and persistent
tracks.  Candidate centroids are converted to integer coordinates.  A track's
matching point is its current point plus its last displacement, giving a
one-frame constant-velocity prediction.  `FUN_18003ca00` uses Euclidean
distance inside a configured radius and an invalid/dummy cost outside it;
`FUN_18003cdb8` performs the global assignment.

Linux `input_mt_assign_slots()` already performs a balanced global
minimum-cost assignment, but Phase 57 passed the raw candidate points and an
unlimited radius.  The substantive missing behavior is therefore prediction,
a finite radius, and explicit lifecycle state—not merely another assignment
implementation.

The offline Phase 58 reference uses the recovered predicted-point cost and
global assignment.  Its 4096-logical-unit gate is a Linux panel fit, not a
recovered Windows setting.  In the 1,381-frame Windows corpus, all consecutive
single-contact motion is below 900 logical units, so the selected gate has
substantial margin while still separating unrelated blobs.

## Lifecycle and smoothing

The Windows code maintains history, active/pre-active/closing state, missing
track handling, and optional forward prediction.  Track updates preserve the
new-minus-old displacement and a ten-entry history.  The exact runtime state
transition thresholds have not yet been recovered.

The recovered smoothing form is an exponential blend:

```text
output = alpha * previous_output + (1 - alpha) * input
```

Windows selects `alpha` through runtime project tuning and motion state.  The
offline reference uses named, conservative fitted bands so the formula can be
tested without presenting guessed values as proprietary facts.  Missing
contacts are held at the last output point; optional Windows forward
extrapolation is deliberately disabled until its activation policy is known.

## Calibration and palm classification boundary

Heat-byte calibration is still consistent with identity gain/offset on this
panel.  Changing it adaptively without a recovered configuration or labelled
physical targets could make coordinates worse.  Coordinate edge compensation
is a separate stage and will require measurements against known screen points.

Windows computes blob shape/covariance and NSR features before classification.
`FUN_180041fd8` derives covariance eigenvalues, an aspect-ratio feature, and a
normalized spread feature after centroid creation. `FUN_18003c048` selects an
NSR threshold from either a curve or a location-indexed table and clears the
blob-valid flag when the measured feature fails it. The runtime table values
are still unnamed and have not been recovered from a live initialized object.
Its palm logic also accepts pen-proximity state.  This project is finger-only,
so pen-dependent palm rejection will not be ported.  A conservative
finger-only classifier can use the verified shape features once its runtime
threshold table is recovered; Phase 57's broad size/span guard remains the
safe fallback meanwhile.
