# Phase 62 project-0x0c83 classifier extractor

Phase 62 resolves how the embedded project database reaches the four-score
shape classifier and adds a safe, offline model extractor. It changes no
kernel code and enables no contact filtering.

## Proven pointer path

`FUN_18005d660` selects the version-4 PSDB for the panel project ID.
`FUN_18005daa8` validates its variable-length records. During detector setup,
`FUN_18008d2d8` passes PSDB `+0xdd0` as the fifth argument to
`FUN_18004a918`; `FUN_180043e58` stores that pointer at detector-state
`+0x16818`.

Consequently, the offsets consumed by `FUN_1800406a8` are relative to the
classifier subsection at PSDB `+0xdd0`, not to the PSDB header and not to a
separately decoded heap object.

The supplied `TouchPenProcessor0C83.dll` contains one matching blob at file
offset `0x828f90`, recorded length `0x9d3b`. At the corrected subsection base,
the four point-count limits are `25`, `9999`, `30`, and `50`; all 220
upper-triangular transform values, 40 means, four biases, eight decision
constants, and feature masks are finite and structurally valid. The project
feature masks are all zero.

## Reproducible extraction

The DLL remains outside the repository and is ignored by Git. Run:

```bash
python3 tools/extract_windows_classifier.py \
  /path/to/TouchPenProcessor0C83.dll \
  --project 0x0c83
```

The output reports bounded metadata and model summaries without writing any
files. Supplying ten values with `--features` evaluates both recovered decision
branches:

```bash
python3 tools/extract_windows_classifier.py \
  /path/to/TouchPenProcessor0C83.dll \
  --features F1 F2 F3 F4 F5 F6 F7 F8 F9 F10
```

The scorer mirrors `FUN_1800406a8`: masked mean subtraction, the ten-row
upper-triangular transform, squared-distance accumulation, point-count limits,
profile bias, and runtime offset. It also masks feature 10 when Windows' 100.0
unavailable-halo sentinel is supplied. Both `+0x1c0` and `+0x1c4` decision
variants are emitted because the surrounding temporal predicate is not yet
labelled.

Synthetic PSDB tests exercise blob discovery, bounds, transform extraction,
point-count disabling, feature masks, the unavailable-halo sentinel, and both
score branches without embedding Microsoft data.

## Remaining boundary

The scorer is exact only when its ten inputs are exact. The primary point
count, covariance-axis ratio, and normalized spread are available offline.
The three secondary detector reruns use candidate-dependent thresholds,
hysteretic neighbour attachment, union merging, and component-state pruning;
the halo ratio uses a two-ring morphological walk. Those stages still require
faithful ports before corpus scores can be treated as Windows-equivalent.

Class labels and temporal state transitions also remain unproven, so the
scores are diagnostic and must not drive live finger rejection yet.
