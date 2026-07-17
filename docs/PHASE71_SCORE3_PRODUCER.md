# Phase 71 recovered class-three score producer

Phase 70 proved that the panel, QSPI/GPI-DMA transport, Heat parser, detector,
and multi-candidate extraction remained healthy, but its opt-in lifecycle
profile emitted no Linux contacts. A bounded live probe found that every track
remained in Windows class four even though ordinary candidates consistently
won classifier class zero.

## Live failure boundary

During a 30-second input capture the target recorded 1,630 GPIO51 interrupts
and 4,898 GPI-DMA interrupts but zero events from `/dev/input/event1`. Dynamic
detector logging showed valid class-zero components, including simultaneous
two- and three-component frames. A temporary read-only kernel probe then
captured score vectors such as:

```text
age=1 old=4 pixels=12 scores=[-83051677,-263186607,-228695744,-219620178]
age=5 old=4 pixels=9  scores=[  1083998,-259751188,-215055929,-186643911]
```

The recovered 4-to-0 transition requires class zero to exceed class three by
30 score units. Phase 70 generated the project score-three penalties but did
not apply them, so otherwise valid contacts could not cross that margin.

## Exact producer recovered in Ghidra

The missing inputs are no longer treated as opaque provider fields:

- `FUN_180040438` scans every candidate cell and calls `FUN_180043000` on its
  four orthogonal neighbours. It stores at most ten local maxima in candidate
  byte `+0x4d`, resolving a two-cell equal-signal plateau by linear index.
- `FUN_180041fd8` counts those maxima whose signal is strictly greater than
  the DLL constant `0.04` and writes candidate byte `+0x4e`.
- `FUN_180049638` subtracts project `+0x8d0` (`50.0`) from class-three score
  when `+0x4d == 1`; otherwise it subtracts project `+0x8d4` (`20.0`) when
  `+0x4e == 1`.

The neighbour-comparison epsilon is `0.0001`. Adjacent values in the observed
eight-bit lookup path differ by about `0.0022203543`, so Q20.12 ordering is
identical for panel bytes. The kernel implements the producer from the raw
candidate bitmap, applies the strict 0.04 filter, and executes the recovered
if/else-if score adjustment before winner selection and transition history.
The default Phase 68 path remains byte-for-byte behaviorally unchanged because
this postprocessor runs only with `windows_orchestrator=1`.

## Corpus and build validation

The 1,381-frame Windows corpus now computes rather than assumes the producer
fields:

```text
decoded frames:                  1381
accepted contacts:               1113
local peaks raw/strong 1/1:      1089
local peaks raw/strong 1/0:         5
local peaks raw/strong 2/2:        19
fixed-point winner mismatches:      0
assignment Q8.24 mismatches:         0
local-peak Q20.12 mismatches:        0
```

The recovered base-lifecycle diagnostic remains 1,095 class-zero selections,
18 still-unclassified samples, and 1,088 accepted decisions. This matches the
earlier bounded diagnostic while replacing its assumed single-group input
with the actual producer.

All 121 repository tests pass. The generated lifecycle header matches the
operator-supplied DLL, checkpatch reports no findings, and the complete GPI,
GENI-QSPI, and touchscreen module set builds against
`7.1.1-sp11-gpicmp1+` with `W=1 KCFLAGS=-Werror`.

## Deployment boundary

Phase 71 is an isolated one-shot experiment. Its boot entry enables
`g6ts_biosref.windows_orchestrator=1`; it does not replace the root-filesystem
client, the Phase 68 or Phase 70 images, or the saved 7.1.3 GRUB default.
Hardware validation must confirm Linux contact emission, one/two/three-finger
continuity, release behavior, and recovery before this branch can replace the
proven profile.

The isolated image was built from commit
`e6802c77b0f56d2498f83b9eaf59dfe115c8c39f`:

```text
entry id:                  sp11-phase71
command-line marker:       sp11_entry=7.1.1-phase71
client source version:     AB8E656F6CD477A5D5F3319
controller source version: 393A6B36EC5A67BDDC47040
GPI source version:        24B1195ED15A417793F5F0E

f65e637f7ad0e34882c662d91f16e61489c911a642e9cc18e8db6b0b3ab6aa71  initrd
fcefdc928b6e45a8212722c9132b9da2dc1c197fc4890f7a9bab3c31d1584b94  DTB
6f263da75052c54b16d9be21b315beab6b45a2c27c08710d5362b033b4aebf30  kernel
```

After image construction the root-filesystem client was restored to the
Phase 68 source version `E7A094AA381F6556CE14985`. The saved GRUB default
remained `Ubuntu SP11 7.1.3 Baseline 1 (Touch+Audio+WiFi+BT+GPU)` and only the
one-shot `next_entry` was set to `sp11-phase71`.
