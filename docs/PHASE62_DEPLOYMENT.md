# Phase 62 deployment checkpoint

The Phase 59 kernel client and Phase 62 offline tooling were built and
validated on the Surface Pro 11 OLED on 2026-07-15. Phase 60 through Phase 62
do not add live kernel filtering; their classifier work remains offline.

## Isolation

- Boot entry: `sp11-phase62`
- Kernel: `7.1.1-sp11-gpicmp1+`
- Kernel command-line marker: `sp11_entry=7.1.1-phase62`
- Client source version: `BA7EE19711271827373E5E4`
- Proven controller source version: `DB3C77C8E873D6BBA8925E8`
- Proven GPI source version: `FC303CACFF2F7773477482D`

Only `g6ts_biosref` was replaced. The Phase 58 controller, GPI module, kernel,
and DTB remained in use because the Phase 59 commit changes only the client.
The known-good 7.1.3 entry and Phase 58 boot assets were not modified. The
repository contains the GRUB source but intentionally does not contain the
locally built kernel, DTB, initramfs, or compressed module.

## Reproducibility checks

The following checks passed immediately before the cold boot:

```text
python3 -m compileall -q tools tests
make test                                      25/25 passed
make phase55 KDIR=/lib/modules/7.1.1-sp11-gpicmp1+/build
```

All three build products had matching
`7.1.1-sp11-gpicmp1+ SMP preempt mod_unload modversions aarch64` vermagic. The
built, installed, and live client source versions were identical.

Local deployed-artifact SHA-256 values:

```text
976e8218d30d23834c592508d9c65bf84f2868eff9daa69e8c9929292e136c41  initrd.img-7.1.1-sp11-gpicmp1+-phase62
fcefdc928b6e45a8212722c9132b9da2dc1c197fc4890f7a9bab3c31d1584b94  sp11-7.1.1-phase62-hybrid.dtb
6f263da75052c54b16d9be21b315beab6b45a2c27c08710d5362b033b4aebf30  vmlinuz-7.1.1-sp11-gpicmp1+
b789cae29005ffa4ff482f430fac6aaeff56674c5aa60420a494a734a08a92ed  g6ts_biosref.ko.zst
```

## Cold-boot result

The dedicated entry booted successfully and bound `spi0.0` to `g6ts-dma`.
The input subsystem registered `Microsoft Surface G6 Touch (DMA)`. The panel
returned its 1,484-byte report descriptor, entered mode stage 4, and enabled
heat mode.

The first sampled live state contained:

```text
fatal_transport_error=0
heatmap_reports=842
heat_decode_errors=0
contact_frames=825
nsr_valid=1
nsr_bins=16
nsr_cutoff=655
nsr_rejections=0
tracker_matches=821
tracker_new=4
tracker_dropped=0
recovery_requests=5
recovery_successes=5
recovery_failures=0
last_ret=0
```

During a subsequent 25-second live window, interrupt edges increased from 893
to 1,600 and decoded contact/idle frames increased from 842 to 1,548. The NSR
metadata remained valid, the maximum observed bin value was 1, and the reset
recovery counters remained fixed at five successes and zero failures. No new
touch-driver warning, decode error, transport error, timeout, or abort was
logged.

The five successful recoveries reflect bounded handling of panel reset
notifications during the earlier active period. They are not recovery
failures, but periodic reset frequency remains an area for longer-duration
measurement.
