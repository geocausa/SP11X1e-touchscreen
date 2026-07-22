# Phase 91 production DMA baseline

## What is promoted

Phase 91 is the hardware-validated production profile for the OLED Surface Pro
11 `MSHW0485` touchscreen on `7.1.3-sp11-baseline1+`. It combines:

- the Phase 75 Linux-integrated QSPI protocol-9 and GPI-DMA transport;
- the hardware-proven Phase 75 power/reset sequence;
- the recovered Windows initialization, device configuration, bounded CFU
  no-update inventory, and final Heat admission chronology;
- the Phase 76 Windows-derived contact behavior;
- the measured Windows response cadence: 490--550 microseconds between a
  valid header and its body, with one complete response serviced per IRQ;
- bounded host-fault recovery and ready-line quiescence.

It does not enable the experimental Windows GENI register sequence or Windows
GPI ring layout. It does not flash firmware, send a CFU payload, or implement
pen support.

## Validation caveat

The promotion is based on two clean cold boots and focused login-screen,
typing, and multi-touch stress. It has not yet completed an extensive
multi-day real-world soak. Treat Phase 91 as the best current baseline for the
tested OLED SP11 and exact kernel, not as a universal stability guarantee.
Retain both the previous DMA and FIFO fallback entries.

## Root cause and hardware result

Phase 90 reached Heat and decoded 1,984 valid frames, then immediately tried a
second header read while GPIO51 remained asserted. The returned bytes were not
a valid HID-SPI header, the stream desynchronized, and six genuine panel reset
notifications followed under active touch.

The stable Windows SPB trace independently shows:

```text
complete Heat responses: 1381
header RX -> body TX minimum: 490.0 us
header RX -> body TX median: 504.8 us
Heat body RX -> next Heat header TX minimum: 2735.0 us
next-header gaps below 1 ms: 0
```

Phase 91 applies only that scheduling difference. Its two cold-boot tests,
including deliberate touch 8.894 seconds after startup at the login screen,
completed:

```text
Heat frames: 14950
panel resets: 0
invalid-header/protocol errors: 0
transport errors: 0
host-fault recoveries: 0
Heat errors: 0
```

This is strong causal evidence that the recurring storm was initiated by a
host-side response overread. It is not a claim that every panel-firmware fault
or future kernel regression is impossible.

## Evidence identities

```text
Windows SPB CSV:
0209583a33f180bf7cd76d17c90ba16da3a37a93921253c2e667af40ebcb1514

Phase 90 filtered controller/client log:
8acc3086c9118499cf2ac04533b4c8cfde91b777cd6f4bfaa1849aeeaa9fbf22

Phase 91 first-boot filtered log:
cafdc38b885d72818678d58a1b2dffb7613f366726e543d1924ad9f812f28cd8

Phase 91 immediate-login filtered log:
c760ff3f55655e33a80c4788cfbad742a403ba7775d992780cc3920aba2a0de4
```

The implementation is anchored at commit `429b2ed`; the two hardware results
are recorded by `d48060f` and `7c98241`. The original large Windows traces and
Microsoft binaries are intentionally not redistributed. Their identities,
derived observations, packet boundaries, and reproducible analysis tools are
retained in this repository.

## Boot layout

`scripts/promote_phase91_dma_baseline.sh` intentionally leaves only three
active SP11 custom entries:

1. `sp11-dma-baseline` -- Phase 91, the saved default;
2. `sp11-dma-previous` -- the previous Phase 75 DMA rescue image;
3. `sp11-baseline-fifo` -- the retained FIFO fallback.

Old menu scripts are copied with checksums to
`/var/lib/sp11-touchscreen/grub-archive/`. Their `/boot` assets are not deleted,
so a laboratory entry can be restored without reconstructing its initramfs.

## Reinstall and recovery

The complete independently written touchscreen source, tests, boot recipes,
deployment scripts, derived findings, and small auditable KDNET log are in Git.
The matching base kernel and platform bundle are published separately in
[SP11Bundle](https://github.com/geocausa/SP11Bundle), release
`sp11-enable-7.1.3-sp11-baseline1-20260713`.

For a fresh installation:

```bash
git clone https://github.com/geocausa/SP11Bundle.git
git clone https://github.com/geocausa/SP11X1e-touchscreen.git
cd SP11X1e-touchscreen
make KDIR=/lib/modules/7.1.3-sp11-baseline1+/build
sudo ./scripts/deploy_phase75_identity.sh
```

Boot and validate Phase 75 once, then return to the repository and run:

```bash
sudo ./scripts/deploy_phase91_windows_cadence.sh
```

Boot Phase 91, verify that touch works and `behavior_stats` has zero fault
counters, commit or discard any local source changes, then promote it:

```bash
sudo ./scripts/promote_phase91_dma_baseline.sh
```

The repository cannot recreate private multi-gigabyte ETL/KDNET/Ghidra stores
that were never published. Those are not needed to build or run the driver;
they remain valuable only for further reverse engineering. Keep a separate
offline backup if future byte-level re-analysis is desired.
