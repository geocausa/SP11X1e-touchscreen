# Phase 69 Windows processing parity

Phase 69 freezes the working Phase 68 kernel behavior while the proprietary
post-detector pipeline is reconstructed offline. No Phase 69 lifecycle or
tracking experiment is deployed until its Windows control flow can be tested
against saved Heat frames independently of the live input device.

The reference component is:

```text
TouchPenProcessor0C83.dll
SHA-256 615a28136f14678298dcd9f009c9295456a9e7ce878717b58d371d343b4c7132
project  0x0c83
```

## Why tuning is deferred

The current Linux client contains explicitly fitted policy:

- a 4096-logical-unit association gate;
- three/five/eight-frame candidate confirmation;
- six-frame track retention;
- two fitted coordinate-smoothing bands and blend factors;
- broad size/span palm rejection.

Those safeguards produced a useful working baseline, but they are not the
Windows project policy. Tuning them further before inserting the missing
classification history, lifecycle, output eligibility, and edge-coordinate
stages could tune around behavior that later disappears. Phase 69 therefore
does not add the adjacent experimental adaptive-MAD threshold patch and does
not change the running module.

## Corrected Windows transition layout

`FUN_180041150`, `FUN_180045038`, and `FUN_180044db0` prove that the project
table contains 20 records, not 16. There are four output classes and five
source states. Source state four is the unclassified value assigned by
`FUN_180046020` when a track is created.

```text
record = new_class + old_class * 4
old_class: 0..3 classified, 4 unclassified/new track
new_class: 0..3
stride:    0x30 bytes
```

The previously omitted new-track row is:

| transition | history margins | current margins | floor | history | early-age limit |
| --- | --- | --- | ---: | ---: | ---: |
| 4 -> 0 | 0, 6, 1, 30 | 0, 10, 1, 30 | -3 | 2 | 3 |
| 4 -> 1 | 22, 0, 15, 15 | 255, 255, 255, 255 | -9999 | 2 | 0 |
| 4 -> 2 | 1, 3, 0, 8 | 255, 255, 255, 255 | -8 | 4 | 3 |
| 4 -> 3 | 100, 7, 8, 0 | 100, 30, 10, 0 | -20 | 3 | 3 |

Windows evaluates the first sample with the current-score rule for the
unclassified row. On later samples it tries the current-score rule while the
track age is within the transition's early-age limit, then falls back to the
history rule. The history ring holds at most ten samples. A configured depth
greater than ten therefore makes that transition fail rather than creating a
30-sample ring.

`tools/extract_windows_lifecycle.py` now extracts all 20 rules and implements
these two numeric predicates. `BaseClassHistory` deliberately stops at the
score-gate boundary: Windows still applies class metric ranges, context and
environment overrides, and lifecycle/output rules afterwards.

## Corrected absolute classifier scores

The transition floors exposed an older extractor error that winner-only tests
could not detect. `FUN_180043e58` initializes the common score offset with
`log(0.25) - exponent * log(DAT_180044508) / 2`. Direct memory extraction at
`0x180044508` gives bytes `18 2d 44 54 fb 21 19 40`, the double-precision
value `2*pi`. The previous extractor constant `3370280550400.0` was an
incorrect decompiler transcription.

For project 0x0c83 exponent ten, the corrected common offset is approximately
`-10.5757`, not `-145.6164`. Class winners were unchanged because the offset
is common to all four scores, but every absolute transition-floor comparison
was wrong. A regression test now locks the DLL value and formula.

`FUN_180049638` then applies an exact class-three adjustment before tracking:
it subtracts project `+0x8d0` when candidate `+0x4d` equals one, otherwise it
subtracts project `+0x8d4` when candidate `+0x4e` equals one. Project 0x0c83
stores `50.0` and `20.0`. The extractor implements this bounded basic step;
the later context/region overrides in the same function remain separate.

With the corrected common offset, the simple one-component class-three
penalty, and the recovered base transition ordering, the saved 1,381-frame
corpus produces this diagnostic result:

```text
single-contact frames: 1113
selected class 0:      1095
still unclassified:      18
accepted decisions:    1088
rejected decisions:      25
finger onset age 1:       17 sequences
finger onset age 2:        1 sequence
finger onset age 5:        1 sequence
finger onset age 7:        1 sequence
finger onset age 8:        1 sequence
```

This is a base score-gate diagnostic, not claimed final Windows output. It
resets its one-track history on an idle frame and treats each saved ordinary
connected component as candidate `+0x4e == 1`. The class-specific point-count
range is applied, but the remaining class exceptions, class override,
five-state lifecycle, and final output builder can still change those results.
It nevertheless proves why a universal three-frame
Linux confirmation window cannot be called Windows-equivalent: the recovered
base policy accepts most ordinary sequence onsets on their first frame and
delays a small minority by transition evidence.

## Exact association configuration recovered

`FUN_1800453e8` constructs predicted track positions, performs global
assignment, and then applies a squared project radius. Project 0x0c83 stores:

```text
normal radius:                    5.0
single-candidate/single-track:   14.0
special single-pair mode enabled: false
```

The special radius is consequently inactive for this project. These values
are in the processor's internally scaled assignment coordinates, not Linux's
0..32767 ABS coordinate space. `FUN_18003d7a8` proves how the two runtime
scale factors are constructed from the sensor descriptor. With `0.01f` as
the descriptor unit, Windows stores:

```text
x_scale = (x_extent * 0.01) / x_denominator
x_denominator = x_nodes - 1  when layout_mode == 0 and y_inset_count == 0
                x_nodes      otherwise

y_scale = ((y_extent * 0.01) - 2 * y_inset_count * y_inset_pitch)
          / y_denominator
y_denominator = y_nodes - 2 * y_inset_count
                minus one under the same zero-inset/layout condition
```

Track predictions and candidate positions are converted with
`(short)(int)(position * scale + 0.5)`. The assignment is rejected when
`radius_squared <= distance_squared`, so equality is outside the gate.
`tools/windows_tracking_geometry.py` now makes this exact arithmetic
regression-testable.

`FUN_18008f3f8` maps the runtime fields back to the selected PSDB sensor
record. For project 0x0c83 sensor zero, the record contains 68 X nodes, 46 Y
nodes, X/Y extents 27189/18053 hundredths, zero Y insets, and layout mode zero.
With the DLL's float32 rounding, the exact assignment factors are:

```text
x_scale = 4.0580596923828125
y_scale = 4.011777877807617
```

`AssignmentScaleInputs.from_dll` extracts those inputs from an operator-
supplied DLL and reproduces each float32 arithmetic stage. The correct kernel
port must retain sensor-space centroids through assignment and quantize X and Y
separately; replacing this with one circular radius in the 0..32767 output
space would change the anisotropic Windows gate.

The post-score point-count ranges at project offsets `+0xde4` and `+0xdf4`
are:

```text
minimum: 0, 6, 4, 4
maximum: 20, 9999, 50, 100
```

Candidate `+0x38` is the component point count: `FUN_1800406a8` compares the
same field with the per-model maximum point counts before classification, and
assignment copies it to track `+0x2e`. It maps directly to the Linux connected
component pixel count.

## Context state is a bounded frame window

All real writes to processor context `+0x16792` have now been located.
Initialization clears it. `FUN_18004a1b8` subsequently sets it once per frame
from the logical OR of three inputs: processor `+0x166c9`, a nonzero bounded
countdown, or byte `+0xba` in the frame subobject passed to that function.
The project stores a 300-frame maximum at `+0xe7a` and enables reset from its
tracked source at `+0xe98`.

The countdown is armed by the lifecycle/output path in `FUN_1800468c0`, which
stores the current 16-bit scan identifier and the 300-frame maximum. Later
frames derive remaining time from that origin, including the DLL's explicit
16-bit wrap expression; it is not a generic wall-clock timeout. Candidate and
track context helpers then optionally refine this global state with region and
proximity tests when project `+0xe99` is enabled (it is one for 0x0c83), using
project distance ten from `+0xe9a`.

`ContextWindow` represents the proven global update and wrap behavior offline.
The three producer flags remain structurally named until their frame-object
provenance is finished, so the oracle does not silently label them as pen,
palm, or finger state. This recovery is significant for typing behavior:
Windows can keep a changed classification branch active for hundreds of scan
frames after the event that armed it.

## Evidence boundary

### Exact and already represented offline

- Heat transport framing and saved 1,381-frame corpus decoding;
- detector thresholding and four-connected components;
- NSR metadata mapping and strict cutoff;
- ten classifier features and four fixed-point scores;
- predicted-position global assignment structure;
- the 20 transition records, current-score predicate, history predicate, and
  ten-sample history capacity;
- new-track unclassified source state;
- project association radii and class metric ranges;
- project sensor geometry and exact float32 assignment scales;
- direct X/Y track updates, separate velocity, running coordinate bounds, and
  direct normal-contact X/Y output;
- the complete arithmetic and ordering of `FUN_180049880`'s output-code
  override, with structurally named external predicates.

### Adapted in the current kernel

- association coordinate gate;
- confirmation and missing-track windows;
- coordinate smoothing (now proven to be a Linux-only adaptation, not a
  recovered Windows coordinate stage);
- palm/large-component rejection;
- mapping from candidate class to final Linux contact.

### Still required before kernel replacement

- retaining sensor-space centroids through Linux assignment and applying the
  recovered per-axis quantization before output normalization;
- exact placement of the recovered point-count ranges among the remaining
  post-score class-specific exceptions;
- producer provenance for the remaining global-context and region-map flags
  consumed by the now-modelled `FUN_180049880` output-code override;
- all five lifecycle-state transitions in `FUN_180043b10` and
  `FUN_180048e70`;
- final eligibility and output construction in `FUN_180049458`;
- physical-edge centroid/clamp behavior in `FUN_180047078`;
- recovery of the non-coordinate scalar blend in `FUN_18004a330` if that
  metric proves relevant to finger-only output policy;
- the remaining special/release branches in `FUN_1800426d8` and their project
  counters;
- runtime configuration provenance. KDNET did not observe a large panel HID
  calibration report, so panel-supplied tuning is not assumed.

Pen-specific behavior remains out of scope by operator choice. Palm behavior
that depends on pen proximity will not be copied into the finger-only path;
finger geometry and multi-contact palm rules remain in scope.

## Exact output-centroid edge rule

`FUN_180047078` recomputes an accepted component's output centroid from a
one-cell-expanded window. It uses calibrated signal above a selected baseline,
temporarily admits qualifying adjacent cells belonging to the same component,
and writes a weighted X/Y centroid. This is a later output-geometry pass, not
coordinate smoothing.

When and only when a component is one cell wide on the far X boundary, or one
cell high on the far Y boundary, Windows calls `FUN_180054690`. The helper
rounds to the nearest integer (C `roundf` semantics) and keeps that integer
only if the centroid is within `0.0001f`; otherwise it returns the centroid
unchanged. The exact bounded snap is represented in the offline geometry
module. The expanded-window baseline/context branches still need recovery
before the full centroid pass can replace kernel code.

## Windows does not exponentially smooth tracker X/Y

Full decompilation of `FUN_18004a330` corrects an important earlier
interpretation. On every matched update Windows:

1. increments track age;
2. stores `candidate_x - old_x` and `candidate_y - old_y` as velocity;
3. copies candidate X/Y directly into current track X/Y;
4. expands the track's min/max coordinate bounds;
5. stores the exact candidate position in its ten-entry history ring.

The exponential expression in that function blends candidate `+0x2c` into
track scalar `+0x18`. It does not read or write the X/Y fields. A search of all
2,464 decompiled DLL functions found only four users of the assignment scale
fields and no hidden second coordinate filter. Finally, normal-contact builder
`FUN_180041b80` copies the selected track/history X/Y floats directly into the
output record.

`TrackKinematics` in `tools/windows_tracking_geometry.py` now represents the
proven coordinate behavior. The Phase 68 Linux smoothing remains frozen only
because it is part of the known-working baseline. It will be removed when the
recovered lifecycle/output pipeline replaces that baseline as one coherent
change, rather than being tuned further.

## Exact post-output duplicate merge

`FUN_180049458` calls `FUN_1800426d8` to build output records, then calls
`FUN_180045228` as a distinct duplicate/merge pass. The merge pass considers
only output record types one and three, requires different group identifiers,
and compares their raw output X/Y with a strict squared-distance predicate.
For project 0x0c83 the ordinary squared-distance limit at PSDB `+0xb90` is
`36.0`. When the frame-wide maximum flag exceeds the project `+0xe78` limit,
the selected alternate value at PSDB `+0xb98` is `0.0`, which disables pairs.

All qualifying pairs are collected before identifiers are changed. In a
second pass, every record carrying the later pair's identifier is assigned the
earlier identifier; paired records of type one become type seven; and both
source tracks receive the merge flag. Equality with the threshold is rejected.
`merge_nearby_output_contacts` represents this ordering and chained-identifier
behavior offline without inventing a Linux-distance conversion.

## Exact output-code override arithmetic

`apply_output_code_override` now mirrors all three ordered branches of
`FUN_180049880`. The project parameters are extracted from the operator's DLL
rather than inferred from live tuning. For project 0x0c83 they include:

```text
ordinary age window:       6..8
context age adjustment:       +2
score-two floors:          -17 / -10
pen distance squared:       215
candidate/default margins:    6 / -10
context/pen margins:        -10 / 0
minimum branch counter:       4
forced-output age/counter:    35 / 10
score-three low floor:       -20
```

The first branch can change ring output code four to code two from averages of
the previous, non-disabled score samples. It applies the recovered pen-source
distance, sensor-edge flags, global context, region exclusion, accumulated
metric, counter, and signal predicates with the DLL's exact strict/inclusive
comparisons. The second branch deliberately tests the code captured at
function entry, so two consecutive low-score samples can overwrite that new
code two with code one. The final age/counter branch is not restricted to an
entry code of four and can set code one after age 35.

The remaining context/region inputs stay structurally named. Synthetic tests
lock branch ordering, equality behavior, and the code-two-to-code-one
overwrite.

## Candidate edge flags and pen-context boundary

`FUN_1800489a0` proves the candidate flags consumed by the override. Candidate
`+0x49` is set when its component bounds touch any outer sensor row or column;
`+0x4a` is set when two boundaries are touched and the component is therefore
at a sensor corner. Candidate `+0x48` is a separate centroid-near-edge flag,
using the project edge margin plus `0.5` while local context is active.
`candidate_edge_flags` models the ordinary grid predicates. The descriptor-
specific seam flag at `+0x4b` remains separate.

The source point at frame `+0xb85c` is passed to `FUN_180046578`, which computes
a transformed 0..359-degree candidate-to-source angle. `FUN_180048548` compares
that angle with the orientation fields at frame `+0xb938/+0xb93a` and the
project orientation windows. This is the pen-orientation/proximity path, not a
second finger tracker. Because pen support is explicitly out of scope, the
finger-only oracle uses the no-source branch instead of inventing source
values.

## Lifecycle and output graph recovered so far

The state setter at `FUN_180048e70` maintains two global counts while writing
track `+0x3c`. Assignment creates a track directly in state one and marks it
matched at `+0x47`. The per-frame order is:

```text
assignment -> unmatched-track lifecycle -> class policy ->
state-3 cleanup/output-state collection -> final output construction
```

The proven state edges are:

```text
0 free -> 1 assigned
1 unmatched -> 3 closing, unless the suppression predicate moves it to 4
1 -> 2 through the recovered history/shape continuation predicate
2 or 4, unmatched with exhausted continuation -> 3
3 -> 0 during the following cleanup pass
```

State four is excluded from normal output. States one and two enter the final
builder, but primary finger records are emitted only for classes zero and two.
The flag at track `+0x46` is set for a previous class-zero/class-two to current
class-one/class-five transition and controls that special transition-output
path; it is not a universal normal-output eligibility flag.

## Validation checkpoint

The extractors are reproducible from an operator-supplied DLL and contain no
Microsoft binary or coefficient dump in the repository. Unit tests cover the
20-record layout, unclassified row, both score gates, equality behavior,
context-disallowed current rules, the ten-sample cap, exact gate ordering, and
project matching/point-count fields. Geometry tests cover runtime assignment
scales, quantization, the strict radius boundary, direct coordinate updates,
far-edge snapping, and ordered duplicate merging. The output-override tests
cover project extraction, history averaging, code-two-to-code-one overwrite,
and the strict age boundary. The complete suite currently passes 64 tests.

The saved Windows corpus regression decodes all 1,381 frames with zero errors,
scores 1,113 contacts with zero floating/fixed-point winner mismatches, and
retains the previously recorded base-lifecycle distribution. That regression
does not yet claim final Windows output parity because the remaining external
flag producers and special/release output branches are not represented.
