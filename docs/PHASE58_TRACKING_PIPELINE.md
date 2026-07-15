# Phase 58 predicted tracking pipeline

Phase 58 ports the first verified proprietary stages after Windows candidate
extraction while keeping the known-good Phase 57 boot artifact intact.

## Implemented

- Persistent per-slot raw and filtered coordinates, velocity, age, and missing
  frame state.
- One-frame constant-velocity prediction for matching, as recovered from
  `TouchPenProcessor0C83.dll`.
- Euclidean candidate-to-track costs and a global Hungarian assignment.
- A finite 4096-unit matching gate fitted with margin from the Windows corpus.
- Explicit dummy assignment so a far blob starts a new track instead of
  stealing an unrelated identity.
- Six-frame bounded dropout hold with velocity damping and clean release.
- The recovered exponential smoothing form, with named conservative Linux
  motion bands pending the proprietary runtime tuning table.
- Read-only counters for matches, new tracks, releases, dropped contacts, the
  match gate, and the hold duration.
- A separate dynamic-programming oracle and kernel-style Hungarian mirror,
  differentially tested over randomized contact sets.

## Evidence boundary

The prediction, global assignment, Euclidean cost, finite gating structure,
track history, and exponential blend form are recovered Windows behavior.
The numerical 4096-unit gate and smoothing-band alphas are SP11 Linux fits.
They are deliberately named as policy rather than claimed as recovered DLL
configuration.

The 1,381 captured Windows frames contain only zero or one accepted contact,
so they validate parsing, candidate extraction, and realistic one-finger
motion but cannot prove multi-contact identity through crossings. Synthetic
tests cover reordered candidates, crossing motion, far jumps, short dropouts,
jitter, and fast motion. Live two- and three-finger validation remains
required.

## Calibration and classification

The recovered heat-byte calibration is `clamp(offset + gain * raw, 0, 255)`.
All current evidence is consistent with identity gain and offset for the SP11
runtime. Phase 58 therefore does not add a guessed adaptive transform.
Coordinate edge compensation requires labelled taps at known physical screen
points before it can be fitted safely.

Windows candidate processing computes weighted centroid, covariance
eigenvalues, aspect ratio, and an NSR-related feature. Its later weak-blob
function selects a threshold from a runtime curve/table and invalidates the
blob when the feature fails that threshold. Those table values have not been
recovered, and the corpus has no labelled palm contacts. The conservative
size/span rejection stays in place rather than training a palm classifier on
finger-only data. Pen-proximity palm policy remains intentionally out of
scope.

## Validation completed before hardware installation

```text
Python unit tests: 16 passed
Randomized Hungarian/DP differential cases: 200 passed
Windows corpus: 1381/1381 decoded, zero errors
Candidate corpus result: 1113 contact frames, 268 idle frames
Exact ARM64 module build: passed without warnings
Kernel vermagic: 7.1.1-sp11-gpicmp1+
```

The dedicated initramfs must explicitly embed `g6ts_biosref`; Ubuntu's generic
module policy includes the matched GPI and GENI drivers but does not discover
this out-of-tree client. `packaging/initramfs-tools/hooks/sp11-g6ts` provides
the required deterministic hook. Install it only while constructing the
dedicated experimental image, then remove it so unrelated initramfs updates do
not acquire the experimental client.
