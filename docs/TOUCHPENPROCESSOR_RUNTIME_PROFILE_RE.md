# TouchPenProcessor 0C83 runtime profile mapping

## 2026-08-04 checkpoint

The exact installed `TouchPenProcessor0C83.dll` (SHA-256 `615a28136f14678298dcd9f009c9295456a9e7ce878717b58d371d343b4c7132`) contains one validated PSDB v4 project `0x0c83` blob at file offset `0x828f90`, serialized length `0x9d3b`. The existing classifier extractor correctly uses serialized project-config base `PSDB + 0x0dd0`.

Static decompilation independently proves the **runtime** geometry-smoothing block is reached through a pointer installed from the runtime project object at offset `+0x294`. The filter reads a float coefficient at block `+0` and an enable byte at block `+4`; raw geometry is `width = max_x-min_x+1`, `height = max_y-min_y+1`, and when enabled the current dimensions are blended with the prior track dimensions.

A direct serialized-offset hypothesis was tested and rejected. Reading `PSDB + 0x0dd0 + 0x294` in the exact 0C83 DLL yields bytes `64 e5 a8 40 76 a6 36 bf ...`, interpreted as float `5.27800178527832` and byte `0x76`. Those cannot be the recovered alpha/boolean runtime fields. The exact 0C80 project gives the same bytes. Therefore the PSDB is deserialized/rearranged into a different runtime object layout before the `+0x294` block is used. Do **not** treat serialized `+0x294` as the smoothing values.

Recovered initialization chain so far:

- `FUN_18004c008` installs global pointers into one runtime project/config object; `DAT_1809096c0 = runtime_project + 0x294`.
- `FUN_18004b318` dereferences that global block; byte `+4` gates geometry smoothing and float `+0` is the blending coefficient.
- `FUN_18004fb08` calls `FUN_18004c008` for 20 track/processor instances and passes its third argument as the runtime project object.
- `FUN_18003d3a8` tail-calls `FUN_18004fb08` on an owning object at `+0x698`.

Remaining task: trace construction/deserialization of that runtime project object and map its `+0x294` block back to the PSDB source field(s), or recover the values through a safe read-only runtime/telemetry path.
