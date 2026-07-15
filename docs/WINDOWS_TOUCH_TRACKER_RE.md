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
track handling, and optional forward prediction. Track updates preserve the
new-minus-old displacement and a ten-entry class history.

Further analysis of `FUN_180043b10`, `FUN_180041150`, `FUN_180044db0`,
`FUN_180045038`, `FUN_180048e70`, and `FUN_180049458` recovered the following
additional facts:

- the lifecycle status is an integer at track `+0x3c`, with values zero
  through four used by the state setter;
- only lifecycle states one and two are eligible for final finger output;
- a separate output-eligibility flag and allowed-class test must also pass;
- one output transition requires more than one historical sample;
- classification history is stored in a ten-entry ring;
- class changes use transition-specific score and history requirements rather
  than one universal debounce period.

The project-0x0c83 transition blocks start at classifier configuration
`+0x8d8`, use a `0x30` byte stride, and are selected by
`new_class + old_class * 4`. The byte at block `+0x4f` is the minimum history
used by the recovered score-history loop. Its 4 by 4 values are:

```text
old 0: 0, 5, 2, 1
old 1: 8, 0, 4, 30
old 2: 2, 5, 0, 4
old 3: 1, 5, 3, 0
```

The associated signed score thresholds are respectively:

```text
old 0:    0, -500, -25, -45
old 1:   -2,    0, -25, -20
old 2:  -25, -500,   0, -15
old 3:  -25,  -40, -25,   0
```

The four human-facing class labels are not yet proven. These values therefore
describe the recovered temporal mechanism but are not sufficient, on their
own, to drive the exact Microsoft statistical model in Linux.

The recovered smoothing form is an exponential blend:

```text
output = alpha * previous_output + (1 - alpha) * input
```

Windows selects `alpha` through runtime project tuning and motion state.  The
offline reference uses named, conservative fitted bands so the formula can be
tested without presenting guessed values as proprietary facts.  Missing
contacts are held at the last output point; optional Windows forward
extrapolation is deliberately disabled until its activation policy is known.

## Linux lifecycle equivalent

The Phase 63 Linux client implements the recovered control-flow boundary
without copying the embedded Microsoft model matrices. New tracks remain
tentative and are never reported while tentative or coasting. Observable
component quality selects one of three evidence windows:

- three frames for a normal independent candidate;
- five frames for a small candidate or a new candidate near an established
  finger;
- eight frames for a substantially weaker or smaller nearby candidate, which
  is the characteristic transient split seen in the live one-finger trace.

The three/five/eight policy is an independently expressed SP11 safety policy,
not a claim that a particular Linux quality category equals one of the four
unlabelled Microsoft classes. Once confirmed, a track remains confirmed until
it closes, preventing normal shape jitter from making a real finger flicker.

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
