# Phase 56: offline hardening

This pass improves the hardware-validated Phase 55 sources without loading a
new module, writing to the touchscreen, or changing any boot artifact.

## Driver hardening

- The input driver is named `g6ts-dma` instead of `g6ts-dma-lab`.
- Successful QSPI read-pair and ordinary transfer diagnostics now use dynamic
  debug and are silent by default. Warnings, errors, startup, and recovery
  summaries remain visible.
- Manual experiment sysfs controls and captured-report storage are disabled by
  default. They are created only when the read-only module option
  `g6ts_biosref.lab_controls=1` is supplied at load time.
- The read-only `state` file remains available and declares whether laboratory
  controls were enabled.
- A malformed Heat frame releases all Linux contacts and emits a rate-limited
  warning, preventing an old contact from remaining stuck indefinitely.

No transport framing, mode-entry command, reset sequence, contact threshold,
palm boundary, smoothing constant, or slot-assignment behavior was changed.

## Reproducible validation

`tools/regress_heat_frames.py` recursively checks captured report-`0x12`
frames without changing them. It performs the same sparse-grid reconstruction,
modal-baseline tie break, connected-component threshold, palm bounds, and
ten-contact limit as the kernel driver.

The full saved Windows corpus produced:

```text
frames=1381 decoded=1381 errors=0
contact_frames=1119 idle_frames=262 palm_rejections=0 max_contact_pixels=12
baselines=0xb4:1191,0xb5:190
contacts_per_frame=0:262,1:1119
```

The corpus contains single-finger movement and idle frames. It proves parser
and one-contact regression but does not provide labeled calibration targets or
ground truth for merged multi-finger contacts.

Eight synthetic unit tests cover raw and class-1 envelopes, full sparse-grid
reassembly, overlapping and incomplete block rejection, modal-baseline ties,
two separated fingers, broad-palm rejection, and the ten-contact bound. A
source-consistency test also prevents the Python policy constants from silently
drifting away from the kernel implementation.

## Build boundary

The Phase 55 wrapper now rejects a configured release other than
`7.1.1-sp11-gpicmp1+` unless `ALLOW_UNTESTED_KERNEL=1` is explicitly supplied
for source-porting work. All three matched modules compile against the exact
7.1.1 tree and report the expected vermagic.

This pass is compile- and corpus-validated only. It deliberately does not
install the modules, update an initramfs, alter GRUB, reload the live driver, or
claim new hardware validation.
