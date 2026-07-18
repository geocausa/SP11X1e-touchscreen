# Phase 72 KDNET transfer-length erratum

## Correction

The original Phase 72 analysis claimed that Windows sent six logical content
bytes in `SET_FEATURE 0x05` and `SET_FEATURE 0x70`. That claim is disproven by
the same raw capture once its explicit lengths are applied.

The debugger breakpoint printed a fixed 72-byte memory window with `db L48` for
every call to `hidspi!SpbBusWrapper::MultiSpiTransfer`. A memory dump is not a
transfer boundary. The relevant Windows packet builder rounds the eight-byte
HID-SPI write header plus logical content to a four-byte boundary:

```text
packet_len = round_up(8 + content_len, 4)
```

For the captured `0x70` write:

```text
type=03 id=70 txLen=c
e2 00 20 00 | 03 | 01 00 | 70 | 01 | a5 00 02 ...
```

- `content_len = 0x0001`;
- `round_up(8 + 1, 4) = 12 = 0x0c`, exactly matching `txLen`;
- the logical HID content is the one byte `01`;
- bytes `a5 00 02` at offsets 9-11 are clocked inside the rounded transfer but
  are alignment bytes outside `content_len`;
- bytes at offsets 12 and later are only part of the fixed debugger dump and
  are not transferred.

The captured `0x05` write has the same length and the same one-byte logical
content. Thus neither write carries the five-byte tail claimed in the original
analysis.

## Cross-checks

The same arithmetic confirms the unaffected observations:

| Report | `txLen` | `content_len` | Evidentiary result |
| --- | ---: | ---: | --- |
| `SET_FEATURE 0x05` | `0x0c` | 1 | logical content `01` |
| `SET_FEATURE 0x70` | `0x0c` | 1 | logical content `01` |
| `SET_FEATURE 0x56` | `0x10` | 7 | seven-byte token is real |
| `OUTPUT_REPORT 0x09` | `0x48` | 63 | complete 63-byte content is real |
| `OUTPUT_REPORT 0x65` | `0x18` | 16 | complete 16-byte content is real |

## Provenance

The raw capture remains outside the repository in accordance with the project
policy against redistributing Windows captures:

```text
file:   sp11_clean_3events.log
size:   33851 bytes
sha256: fd1f8d439d11a729751fa68ec8788b0a8536b70fe4fc391e853829fe87078ddd
```

The hash was independently reproduced from the copy supplied on 2026-07-18.
The raw file, Claude transcript, and repository implementation were reviewed
against one another before this correction.

## Impact

- The “truncated feature payload” root-cause claim is retracted.
- Phase 72's zero-reset hardware result remains valid.
- The causal mechanism of Phase 72's benefit is unisolated.
- Windows' distinct cold, standby, and device-reset paths remain supported by
  PDB names and captured traffic.
- Full 63-byte report `0x09`, seven-byte report `0x56`, and cold-only 16-byte
  report `0x65` observations remain supported.
- Production Phase 75 remains unchanged pending isolated experiments.
