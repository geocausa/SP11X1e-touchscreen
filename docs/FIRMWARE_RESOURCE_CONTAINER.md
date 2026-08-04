# Surface G6 firmware resource container

The validated 425,818-byte ARC image ends with a structured resource chain,
not an undifferentiated code/data tail. Each record has this layout:

```text
u8    tag
u8[3] marker = 00 00 0e
u32le payload_length
u8    payload[payload_length]
```

The exact chain begins at ARC file offset `0x5f25f`:

| Tag | Header | Payload | Bytes | Contents |
| --- | ---: | ---: | ---: | --- |
| `G` (`0x47`) | `0x5f25f` | `0x5f267` | 1,484 | live HID report descriptor |
| `H` (`0x48`) | `0x5f833` | `0x5f83b` | 12,256 | ZIP containing `GenericCliDescriptor.xml` |
| `I` (`0x49`) | `0x6281b` | `0x62823` | 13,719 | ZIP containing `logger_descriptor_proto.bin` |
| `J` (`0x4a`) | `0x65dba` | `0x65dc2` | 0 | empty record |
| `0xff` | `0x65dc2` | `0x65dca` | 8,589 | zlib-compressed panel configuration |

The final payload ends at `0x67f57`; three trailing bytes remain. Their role is
not yet established.

## Reproducible identities

```text
G / HID descriptor:
  8534961c82edceecc9e21c612be560b9dd9b3bef7df36233059179c58d47fa57

H / ZIP:
  fcf53bb7a2e59a54397d7ec42472041ca216c66bd716d5f4a52547985fa42842
GenericCliDescriptor.xml (49,857 bytes):
  e3e44922fc4689bf47c3e6f8f0c6cabb4e65d1ebbebab56849048bde102a7434

I / ZIP:
  35a9eca1076c32a631d20793c9ad88654237183305582a408f6b99868e0b3292
logger_descriptor_proto.bin (35,978 bytes):
  98439110f8f2e28dc1547f7b658ce85dc3e685597afd94be65263fbba5098fbd

0xff / zlib payload:
  2e44d00b43ca38fde65389d394097f181f729d6bc72e0ac2dbd2408e92fc7a20
expanded panel configuration (169,899 bytes):
  144f219c1b78e34c8b4eef14cff9326742cf1822eb375a4d4cce2b13a3bc894e
```

`tools/extract_firmware_resources.py` finds and validates the complete chain
in either the unwrapped CFU image or the extracted ARC image, then reports
these identities and the ZIP members. It neither changes nor communicates
with the panel. Offsets in this document are ARC-relative; offsets reported
against the complete unwrapped CFU image are `0x680` higher.

## Engineering-interface evidence

`GenericCliDescriptor.xml` declares 274 commands. Particularly relevant names
and their declared semantics include:

- command 36/38: enable and trigger multi-touch on-the-fly calibration;
- command 47: reset firmware;
- command 48: force single-touch;
- command 52: control border masking;
- command 53: force full-frame delivery;
- command 57: select wake-on-touch/display state;
- command 107: select report mode, with `0 = PRE_OS` and
  `1 = Normal (Full Frame)`;
- command 126/127: get/set the multi-touch right shift;
- command 128: read hinge angle;
- command 149: select the finger-effect learning reference window;
- command 155/256: get/set FastHostId;
- command 164..167: get/set display and stitching state;
- command 246/247: get/set cycles retained in multi-touch without contact.

This proves that the shipped firmware distinguishes PRE_OS reports from normal
full-frame delivery and owns substantial acquisition, noise, calibration, and
posture state. Later handler-level analysis rules out HID Feature `0x70` as
the bridge to CLI command 107: Microsoft's installed Surface pen adaptation
driver identifies `0x70` as the host/OOB auto-bonding capability report for
Slim Pen 2 / MPP 2.6 hardware.

The Heat software processor instead identifies Feature `0x05 = 01` as
**Switch Mode Feedback**. It resolves vendor Usage Page `0xff00`, Usage
`0x00c8`, constructs the report from the live HID descriptor, and sends it
during normal Heat initialization. A fresh Windows restart trace enters
continuous 3,636-byte Heat streaming after that switch, while the firmware
engineering interface independently defines report-mode value `1` as
`Normal (Full Frame)`. This makes Feature `0x05` the strongest current
production-HID report-mode candidate. The CLI command IDs and HID report IDs
remain separate namespaces, however, and the table-driven panel-side HID
consumer has not yet been connected directly to command 107 or its underlying
state. See [WINDOWS_FEATURE70_AUTOBONDING_RE.md](WINDOWS_FEATURE70_AUTOBONDING_RE.md)
and [WINDOWS_FEATURE05_SWITCH_MODE_RE.md](WINDOWS_FEATURE05_SWITCH_MODE_RE.md).

The resource describes an engineering interface. Its presence is not evidence
that it is reachable through the production HID path, and the driver must not
issue these commands speculatively.

## Logger evidence

The logger dictionary independently names firmware paths for:

- received display/stitching/hinge feedback;
- V03 and V06 pen feedback and V09 touchpad-threshold feedback;
- multi-touch and self-cap calibration, including interruption on touch, pen,
  hinge-angle change, and screen-state change;
- touch detection, feature extraction, post-processing, and TrackLib contact
  state;
- noise-immunity-driven band, gain, right-shift, and forced-single-touch
  changes;
- firmware resets, retry exhaustion, and fatal-reset reasons.

These names corroborate the Windows producer analysis: report `0x09` carries
real runtime feedback rather than a fixed mode token. They also show that the
panel contains an on-device PRE_OS tracking path. They do not establish which
of those stages are active while the panel is in normal full-frame mode.

## Panel configuration evidence

The expanded `0xff` JSON object is a Denali/Maestro panel configuration. Its
first two channel maps contain exactly 68 and 46 entries, independently
confirming the `68 x 46` Heat grid used by the Linux decoder. It also contains
named acquisition cycles, window definitions, band/gain presets, antenna maps,
and clock settings.

This validates the grid dimensions and exposes future acquisition-side study
material. It does not supply the Windows host-side classifier or tracker
parameters, and those hardware values should not be copied into Linux control
writes without tracing their ownership and lifecycle.

## Why the descriptor had no code references

Ghidra found no references to the resource header, descriptor start, or
interior report-`0x09` declaration. Raw searches also found no ordinary,
big-endian, or halfword-swapped absolute pointers. The resource-chain layout
explains that negative result: consumers can enumerate records by tag and
length without embedding an address to the descriptor.

This narrows the remaining panel-consumer work. Literal searches beside the
descriptor are exhausted; the useful targets are the generic resource/HID
loader and the runtime feedback-dispatch path. Until a subtype handler is
identified, the production driver should retain the hardware-validated Phase
75 exchange rather than replay a dynamic Windows A1/A5 capture.
