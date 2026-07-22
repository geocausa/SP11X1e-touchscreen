# Windows initialization parity boundary

## Purpose

This branch deliberately separates panel bring-up from Heat decoding, contact
classification, tracking, and Linux input.  The first goal is not working
touch.  It is a falsifiable HID-over-SPI initialization path in which every
operation has a captured Windows counterpart, the logical payload is bounded
by `content_len`, and traffic from independent HID collection owners is not
flattened into an invented reset script.

The experimental module option is:

```text
mshw0485_touch.windows_init_parity=1
spi_geni_qcom.sp11_windows_se_init=1
```

It is read-only.  When selected, the driver intentionally leaves
`mode_enabled=0` and creates no touch events after reaching an unresolved
Windows owner boundary.

The exact provider state captured on this SP11 is supplied separately:

```text
mshw0485_touch.parity_display_bitmap=1
mshw0485_touch.parity_stitching_flag=0
mshw0485_touch.parity_hinge_angle=400
mshw0485_touch.parity_fast_host_id=400
mshw0485_touch.parity_report56_identity=0xbc,0xe6,0x4a,0x2e,0x86,0x78
mshw0485_touch.parity_report56_flag=0
```

All are read-only. Missing inputs stop the sequence at the owning boundary;
the driver never substitutes a plausible value.

## Canonical evidence

The raw logs remain private because they contain a complete Windows session.
Their identities are:

```text
f2405158054c4475a5c225446eccc7873af1e1fa1a6066406a34876ea9ca2d23  sp11_touch_deep_boot2_0924_2026-07-18_23-02-40-797.log
431d48d05a78de130f3d05bc0e2132b62ee1ed9cbb71d41bd1abfd20f6858ed4  sp11_touch_deep_20c4_2026-07-18_22-43-41-830.log
ca7ba016fec4dc60f0161ed5ef30d0b6d76334613f930de4f2099aa3742f7050  sp11_touch_deep_boot3_1e90_2026-07-20_07-23-54-390.log
d4c620e66de94318962c2c745fbeec9ff83725bb4c3139652336e56bb271a5c3  sp11_seinit_capture_280c_2026-07-20_08-39-54-630.log
```

`tools/extract_kdnet_hidspi.py` reconstructs completed transfers and enforces
the wire-length and logical-content boundaries.  The new
`tools/extract_windows_bringup.py` adds collection ownership and real reset
boundaries.  The latter is important: Windows serializes the bus, but its HID
collections independently produce requests.

## Complete captured cold order

The unperturbed cold attach at uptime 20.753–26.056 seconds is:

| order | operation | logical content | owner/evidence |
|---:|---|---|---|
| 1 | `RESET_RESPONSE` | empty | HID-SPI core |
| 2 | `DEVICE_DESCRIPTOR` | empty | HID-SPI core |
| 3 | descriptor response | 24 bytes | HID-SPI core |
| 4 | `REPORT_DESCRIPTOR` | empty | HID-SPI core |
| 5 | descriptor response | 1,484 bytes | HID-SPI core |
| 6 | `GET_FEATURE 0x73` | empty | `0xfff4/0x0001` device-config collection |
| 7 | response `0x73` | `fe ff` | captured early state; parity build requires this exact result |
| 8 | `GET_FEATURE 0x06` | empty | `0x000d/0x000f` raw-Heat collection |
| 9 | response `0x06` | 119 bytes | descriptor-declared capability/config data |
| 10 | `OUTPUT_REPORT 0x09` A1 | 63 bytes | FeedbackManager posture/display provider |
| 11 | `OUTPUT_REPORT 0x09` A5 | 63 bytes | FeedbackManager pen provider |
| 12 | `SET_FEATURE 0x05` | `01` | raw-Heat collection |
| 13 | `GET_FEATURE 0x70` | empty | device-config collection |
| 14 | response `0x70` | `02` | two descriptor-declared Boolean bits |
| 15 | `SET_FEATURE 0x70` | `01` | device-config collection |
| 16 | `SET_FEATURE 0x56` | `bc e6 4a 2e 86 78 00` | device-config collection |
| 17 | `GET_FEATURE 0x60` | empty | CFU collection |
| 18 | four `OUTPUT_REPORT 0x65` exchanges | 16 bytes each | CFU inventory/update protocol |
| 19 | `GET_FEATURE 0x73` | empty | device-config collection |
| 20 | response `0x73` | `90 01` | dynamic later state; do not hard-code |

The descriptor body has SHA-256
`8534961c82edceecc9e21c612be560b9dd9b3bef7df36233059179c58d47fa57`
and is byte-identical to the descriptor in the firmware-update image.  The
119-byte `0x06` response in this run has SHA-256
`f6bc0b907c094acd82cb422e88b05aa1ec016f32a791c0d9dc061db46617616d`.

## Provider-gated execution after `GET_FEATURE 0x06`

The A1 and A5 report-`0x09` bodies are fully captured, but a captured value is
not automatically a constant.  Firmware-resource and Windows-binary analysis
identifies report `0x09` as FeedbackManager input:

- A1 carries live display/posture/stitching/hinge state.
- A5 is produced by the pen feedback provider.

Cold capture hashes for the particular observed provider state are:

```text
b2cae0b35eeb4fee62858ee05edfa2a626b48fe1ef14d38b383642d337504008  report09-A1-content-63B
f29901ec43a8efc1058e3242f59bdd8e627faf7e71f0fb1f6ca6df946f8a3a31  report09-A5-content-63B
```

Other captured A1 variants differ, proving at least part of the body is live
state.  Replaying either hash would reproduce one old Windows state, not the
Windows method.  The parity driver therefore stops at
`windows-feedback-required` unless all four provider values are explicitly
supplied.  They default to unavailable (`-1`).

Static call-graph work documented in `WINDOWS_FEEDBACK_ATTACH_RE.md` recovered
the initial A1 and A5 serializers.  With values from this exact SP11 capture,
they reproduce both hashes above byte-for-byte.  The enabled path then requires
the observed `DATA 0xa0={01}` response, emits A5, sends exact
`SET_FEATURE 0x05={01}`, and enters the device-config owner after the observed
inter-owner gap. It strictly requires `GET_FEATURE 0x70={02}`, sends the
one-byte Windows `SET_FEATURE 0x70={01}`, and constructs the seven-byte report
`0x56` from six platform-owned identity bytes plus its Boolean flag.

The identity is not guessed: those six bytes occur in all complete Windows
captures and reappear at GET_FEATURE `0x60` offsets 20, 24, 28, 32, 36, and 40.
Windows sends report `0x56` before the CFU owner reads `0x60`, so reading `0x60`
early would change the method. The parity path instead requires the platform
value as an input, preserves the captured ordering, then stops at
`windows-cfu-owner-required`. Phase 84 does not send report `0x65` and never
admits Heat. The separately installed `SurfaceCFUOverHid.dll`, its exact offer
constructor, and all four responses have since been recovered, but that work
is being kept behind a later checkpoint rather than changing Phase 84 in
place. See `WINDOWS_CFU_BOUNDARY.md`.

## Lifecycle facts that must remain separate

The command previously shown as type `7`, ID `1`, content `03` is the standard
HID-over-SPI `SET_POWER(OFF)` command.  It occurred roughly 17 seconds before a
clean HID child restart.  It is teardown, not vendor mode setup.

The clean restart then used a different multi-owner ordering:

```text
RESET -> DEVICE_DESCRIPTOR -> SET 05 -> GET 70 -> A1/A5 report 09
      -> SET 70 -> SET 56 -> (about 1.93 s) GET 73
```

It did not request the report descriptor or feature `0x06`.  Those objects
were still owned by the surviving parent/collection state.  Debugger-induced
host-timeout recoveries contain still other interleavings.  None is permission
to turn the cold chronology into a synchronous recovery recipe.

## What is exact and what is not yet exact

Exact in the parity path:

- the SP11 ACPI `GTCH._PS0` GPIO ordering (power high, 500 ms, reset high)
  followed by `GTCH._RST` (reset low, 300 ms, reset high); the laboratory
  still forces a preceding `_PS3`-equivalent cold cycle for determinism;
- 40 MHz mode-0, quad TX/RX transaction shape already correlated with Windows
  GPI-DMA descriptors;
- the guarded 13-write QSPI serial-engine initialization order, isolated from
  Linux's generic GENI initialization and mode-selection writes;
- HID-SPI request headers and rounded wire lengths;
- reset, descriptor, early `0x73`, and `0x06` order;
- exact SP11 device descriptor identity and declared limits;
- strict response class, ID, and logical length checks;
- recovered initial A1/A5 serializers with explicit provider inputs;
- exact SET `0x05`, GET/SET `0x70`, and SET `0x56` contents for this SP11;
- Heat and CFU report `0x65` gated at the next independent owner boundary.

Not yet claimed exact:

- parent resource/clock and TLMM ownership surrounding the now-recovered
  serial-engine MMIO transition;
- the host source and encoding of every dynamic A1/A5 field;
- the precise Windows scheduler predicate behind the observed 476 ms gap
  between the Heat and device-config owners (the parity path preserves a
  conservative 470 ms boundary);
- hardware validation of the newly recovered, separately gated CFU inventory
  transaction (no firmware payload path will be implemented);
- the distinct Windows restart, D3/D0, and host-timeout state machines.

These are implementation gates, not invitations to substitute plausible
values.  The stable production entry remains separate while this path is used
as a protocol laboratory.
