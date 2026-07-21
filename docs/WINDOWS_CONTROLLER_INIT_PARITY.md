# Windows QSPI controller initialization parity

## Evidence

The exact installed `qcspi8380.sys` has SHA-256:

```text
34cabf2e7b59d3f8c0608da80dfdc705173c82427611312d32e7c1a9720e33ec
```

Its `FUN_14001b3c8` controller-preparation routine was first recovered
statically, then hit during a cold KDNET boot before normal HID traffic. The
canonical raw log identity is:

```text
d4c620e66de94318962c2c745fbeec9ff83725bb4c3139652336e56bb271a5c3  sp11_seinit_capture_280c_2026-07-20_08-39-54-630.log
```

At uptime 15.984 seconds the function received SE MMIO base
`ffff8605:822d4000`. `GENI_IF_DISABLE_RO` at offset `0x64` was zero, so the
guarded programming block executed. KDNET reads before and after the function
confirmed the persistent values at offsets `0x258`, `0x614`, `0x644`, and
`0xe18`. Clear-on-write or inactive DMA-bank registers correctly read back as
zero.

## Exact guarded write order

When bit 0 of `GENI_IF_DISABLE_RO` is clear, Windows writes:

| order | offset | value |
|---:|---:|---:|
| 1 | `0x258` | `0x00000001` |
| 2 | `0xe1c` | `0x00000000` |
| 3 | `0xe18` | `0x0000000f` |
| 4 | `0x614` | `0x33c00046` |
| 5 | `0x644` | `0x03001e06` |
| 6 | `0xc50` | `0x0000000f` |
| 7 | `0xc4c` | `0x0000000d` |
| 8 | `0xd50` | `0x00000fff` |
| 9 | `0xd4c` | `0x0000001d` |
| 10 | `0x618` | `0xffc07fff` |
| 11 | `0x648` | `0x0fc07f3f` |
| 12 | `0xc44` | `0x0000000f` |
| 13 | `0xd44` | `0x00000fff` |

The direct assignment at `0x258` matters: the Windows routine does not perform
a read-modify-write. The whole block is skipped when the FIFO-disabled guard
is set.

## Linux isolation

The read-only module option is:

```text
spi_geni_qcom.sp11_windows_se_init=1
gpi.sp11_windows_ring_layout=1
```

It is present only in the isolated Phase 84, Phase 85, and Phase 86 entries. For
the SP11 protocol-9 controller it:

- skips generic `geni_se_init()`, whose broad clears, FIFO watermarks, and
  common interrupt enables are not in the captured Windows routine;
- applies the guarded 13 writes in the recovered order;
- skips generic `geni_se_select_mode(GENI_GPI_DMA)`, which would otherwise
  clear and rewrite the just-established state;
- arms the live mask at transfer submission rather than adding a separate
  probe-time mode transition.

The GPI option also selects the captured qcgpi geometry: 16 transfer-ring
elements (`0x100` bytes) per TX/RX channel and 32 event-ring elements (`0x200`
bytes). The existing QSPI scratch words, RX-before-TX submission, descriptor
barrier, and high-doorbell-before-low-doorbell ordering already match the
static and live Windows evidence.

The exact option also emits Windows' bidirectional GO flags `0x00200101`.
Production Linux adds `LINK` (`0x00200901`) because earlier Linux channel
contexts did not advance the pre-doorbelled RX ring without it. Phase 84
deliberately removes that workaround. Failure at this gate is useful evidence
that channel coupling remains a Linux integration mismatch; it must not be
hidden by calling the resulting descriptor Windows-identical.

The default production path is byte-for-byte unchanged unless this option is
explicitly selected.

## Lifecycle boundary

Disabling and re-enabling the HID touchscreen and TouchPenProcessor children
did not hit this routine. Windows leaves the lower qcspi controller alive and
restarts only the HID/protocol layer. Therefore ordinary panel recovery must
not reinitialize the serial engine.

This closes the serial-engine MMIO sequence itself. It does not yet prove
byte-for-byte parity for the parent clock/resource acquisition or TLMM pinctrl
owner, and the new Linux path still requires its isolated Phase 84 hardware
test before it can be called operationally equivalent.
