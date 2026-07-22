# Surface G6 touchscreen firmware-update reverse engineering

## Source identity

```text
file:   SurfaceTouchG6_FW_MSHW0485.payload.bin
size:   468587 bytes
sha256: addfa77b768e0905010766e73117872bc2feddbc8ee9f080322767456e82f1e5
offer:  00 00 12 00 89 14 00 3f ff ff ff ff 04 04 75 00
version: 0x3f001489 (63.20.137)
```

The same payload hash is present in the current Windows driver extraction, the
complete project corpus, and the earlier local driver bundle.

## CFU container format

The payload is 8,221 contiguous addressed records:

```text
u32le destination_offset
u8    data_length
u8    data[data_length]
```

`tools/extract_cfu_payload.py` validates every address and boundary before
unwrapping. The final record starts at address `0x685b0` and contains 42 bytes.

```text
unwrapped size:   427482 bytes
unwrapped sha256: 281c299afccbb02275f972d6c409b950784cb3859c6bed3ef08aeb3083fd139e
```

The signed manifest identifies a firmware block at unwrapped offset `0x66c`.
Its 20-byte inner header is followed at offset `0x680` by a 425,818-byte ARC
image:

```text
ARC image sha256: 319ec4279a6b1922e33da8878c5c56639d5a059642583c6ee4b5a0002d736d48
load address:     0x20000000
processor:        ARCv2 little-endian (firmware identifies ARC_HS/MetaWare G5.8)
```

The analysis project is `/home/geoca/SP11TouchFirmwareARC.gpr`. The import is
kept separate from the open Windows-driver Ghidra project.

The ARC tail is now decoded as a five-record Denali resource chain containing
the HID descriptor, engineering CLI descriptor, logger dictionary, and a
compressed panel configuration. See
[FIRMWARE_RESOURCE_CONTAINER.md](FIRMWARE_RESOURCE_CONTAINER.md) for exact
offsets, hashes, semantics, and the reproducible extractor.

## Exact live-descriptor match

The 1,484-byte descriptor read from the panel in the July 18 KDNET session has
SHA-256:

```text
8534961c82edceecc9e21c612be560b9dd9b3bef7df36233059179c58d47fa57
```

It appears byte-for-byte in the ARC image at file offset `0x5f267`, mapped
address `0x2005f267`. This is stronger than a descriptor-like signature: the
update image contains the exact descriptor served by the running panel.

Relevant declarations include:

```text
85 05 ... 95 01 ... b1 02        Feature 0x05, 1 byte
85 09 09 c9 75 08 95 3f 91 02   Output  0x09, 63 bytes
85 56 ...                         Feature 0x56, 7 bytes total
85 70 ...                         Feature 0x70, 1 byte total
85 65 ...                         Output/Input 0x65, 16 bytes each
```

The descriptor proves report sizes and vendor collections, not the semantic
meaning of each byte in a report-`0x09` payload.

Collection order provides another independent cross-check. Report `0x09` is
inside the second top-level application collection, the raw-heatmap collection
used by the touch-processing stack. Report `0x65` is inside the sixth top-level
application collection, beginning at descriptor offset `0x3f4` (1012). That
matches the firmware-update INF's `HID\VEN_MSHW&DEV_0485&Col06` target. The
collection identity, version match, and cold-only lifecycle all point to CFU;
none points to report `0x65` being required for ordinary touch mode.

## Lifecycle correlation

GET `0x60` returns `89 14 00 3f` at content offsets 4..7. Windows' cold-only
third report-`0x65` write contains:

```text
00 00 12 a0 89 14 00 3f ff ff ff ff 04 04 75 00
```

This mirrors the CFU offer, including the exact firmware version. The `0xa0`
byte is transport/collection context and must not be silently normalized to
the offer file's zero. Reports `0x60` and `0x65` therefore belong to firmware
inventory/update management, not the minimum touch-mode handshake.

No complete captured report-`0x09` variant and no SET-`0x56` token occurs as a
literal sequence in the firmware image. Those values are constructed or
derived at runtime; static byte searching cannot supply their ownership.

## Ghidra state and limits

The ARC image has been imported with the correct base and processor. A
two-byte-aligned pointer scan seeds 788 unique candidate entry points for
analysis. Ghidra's ARCv2 module reports some invalid delay-slot/offcut warnings,
so decompiler output must be confirmed against instruction flow before it is
used as protocol evidence.

The Windows-side producer of the A/B/C variants is now traced in
[WINDOWS_REPORT09_FEEDBACK_RE.md](WINDOWS_REPORT09_FEEDBACK_RE.md). It proves
that the reports carry dynamic display, persistent-host, feedback-manager and
provider state, including retained bytes. The remaining useful static target
is the panel-side HID output dispatcher and the state changed by each
report-`0x09` subtype. Until both sides agree, no full report-`0x09` replay
belongs in the production driver.

An ARC-wide follow-up searched 1,341 seeded functions for an explicit
`0xa5` comparison or switch case and found none. The only ordinary function
containing an `0xa5` scalar uses it as a structure offset, not a feedback
subtype; the other candidate is an invalid/offcut decode in descriptor/data
space. Combined report-ID/length scalar searches likewise resolve to CFU or
unrelated structure constructors. Cross-reference and encoded-pointer searches
to the descriptor header, start, and report-`0x09` declaration also found
nothing. The newly decoded resource framing explains why: the descriptor is
record `G` in a tag/length-enumerated container rather than ordinary addressed
program data. The negative result remains consistent with a table-driven
generic HID dispatcher or forwarding the feedback envelope to a second
firmware component, but it does not prove either design. The consumer must
therefore be reached from generic resource/HID registration flow rather than
another literal-value search.
