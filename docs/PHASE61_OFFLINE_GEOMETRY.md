# Phase 61 offline Windows geometry tracer

Phase 61 adds no live-kernel policy. It ports two scale-invariant geometric
features from `TouchPenProcessor0C83.dll` into the read-only Heat-frame tools so
that captured contacts can be compared with the later Windows classifier.

For each four-connected signal island, `tools/decode_heat_frame.py` now emits:

- signal-weighted row and column variance and covariance;
- major and minor covariance axes using the DLL's
  `4.618800163269043` multiplier and minimum-axis clamp of 1;
- the candidate `+0x8c` major/minor axis ratio;
- the candidate `+0x90` normalized spread, computed as covariance trace times
  `6.2831854820251465 / (point_count - 1)`, or 1 for a single point.

The recovered signal lookup is linear, so multiplying every signal weight by a
constant does not change the centroid or covariance. The existing offline
`180 - raw` weights are therefore sufficient for these two features.

`tools/regress_heat_frames.py` reports the minimum and maximum axis ratio and
normalized spread across accepted contacts. This establishes capture-corpus
bounds without rejecting, relabelling, or smoothing any contact.

The complete saved Windows corpus produced:

```text
frames=1381 decoded=1381 errors=0
contact_frames=1113 idle_frames=268 palm_rejections=0
nsr_metadata_frames=1381 nsr_rejections=0 nsr_value_max=2
contacts_per_frame=0:268,1:1113
windows_geometry_bounds=axis_ratio:1.001656..1.605412 normalized_spread:0.583089..1.328390
```

The accepted-contact counts are identical to Phase 59, confirming that the new
fields are observational and do not alter policy.

The remaining Windows classifier work is deliberately separate:

1. reproduce its three secondary detector reruns;
2. reproduce its surrounding/halo energy ratio;
3. validate all four score streams and temporal states against labelled data.

Until those steps are proven, these features remain diagnostic-only.
