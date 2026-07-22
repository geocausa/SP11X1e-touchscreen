# KDNET outgoing mode-setup capture, 2026-07-17

This directory preserves a byte-for-byte copy of the supplied live KDNET
capture from the actual Surface Pro 11 Windows installation.  The raw log is
the primary evidence.  `SUPPLIED_ANALYSIS_UNCORRECTED.md` is archived only for
provenance and **must not be treated as canonical analysis**: its claim that
Windows sends six logical bytes for `SET_FEATURE 0x05`/`0x70` is contradicted
by the capture's explicit lengths.

## Integrity

See `SHA256SUMS`.  The raw-log hash matches the independently reported hash:

```text
fd1f8d439d11a729751fa68ec8788b0a8536b70fe4fc391e853829fe87078ddd
```

## Packet boundary facts

The breakpoint printed `txLen` in hexadecimal and dumped 0x48 bytes from the
outgoing packet buffer.  The packet format visible in the capture is:

```text
offset 0..3   transport header
offset 4      report type/class
offset 5..6   logical content_len (little endian)
offset 7      report ID
offset 8..    logical content, followed by transfer-alignment padding
```

Consequently:

* Report ID `0x09`: `content_len=0x003f`, `txLen=0x48`.  All 63 logical
  content bytes and the single alignment byte were captured.
* `SET_FEATURE 0x05`: `content_len=1`, `txLen=0x0c`, logical content `{01}`.
* `SET_FEATURE 0x70`: `content_len=1`, `txLen=0x0c`, logical content `{01}`.
* `SET_FEATURE 0x56`: `content_len=7`, logical content
  `{bc e6 4a 2e 86 78 00}`.
* Report ID `0x65`: `content_len=16`, `txLen=0x18`.

For the one-byte `0x05` and `0x70` writes, bytes at packet offsets 9..11 are
clocked only as round-up padding.  Bytes shown after offset 11 were outside
`txLen` and were not transferred.  Neither region extends the logical HID
content beyond `{01}`.

## Complete report-09 payloads

Eleven report-09 writes occur in the log.  They reduce to **five**, not four,
unique 63-byte logical payloads.  The hashes below cover the 63 content bytes,
starting with `8e` and excluding the transport/HID headers and alignment byte.

| Label | SHA-256 of 63-byte content | Nonzero content offsets (`offset:value`) |
|---|---|---|
| R09-1 | `b2cae0b35eeb4fee62858ee05edfa2a626b48fe1ef14d38b383642d337504008` | `0:8e 1:a1 2:01 4:90 5:01 40:90 41:01` |
| R09-2 | `f29901ec43a8efc1058e3242f59bdd8e627faf7e71f0fb1f6ca6df946f8a3a31` | `0:8e 1:a5 3:02 39:90 40:01 46:40` |
| R09-3 | `151326b1dfb63ef02ad1f3811bb0248ed638190e5b2357b1ed4605132562fb58` | `0:8e 1:a5 2:01 3:02 12:70 13:17 36:ff 37:f8 39:90 40:01 43:04 44:ff 46:52 47:43 48:ff 49:02` |
| R09-4 | `ace108e9eba1dcca0df5df960ed8c247e77b90b5a3ead2994dd9108b4c1943c3` | `0:8e 1:a1 4:90 5:01 40:90 41:01` |
| R09-5 | `aad25b0837295b7af8ee3ad87c7056c99a684c788cfc67b5d139fc92777ababe` | `0:8e 1:a5 3:02 12:70 13:17 36:ff 37:f8 39:90 40:01 43:04 44:ff 46:40 48:ff 49:02` |

R09-3 and R09-5 demonstrate that report 09 contains lifecycle/runtime-dependent
state.  A single zero-filled template is not byte-equivalent to every Windows
write.

## Observed outgoing order

The initial block, described by the capture operator as cold startup, is:

```text
09(R09-1), 09(R09-2), 05{01}, 70{01}, 56{token}, 65 x4
```

The block described as standby wake is:

```text
09(R09-3), 09(R09-4), COMMAND_CONTENT 01{03}
```

After the device-reset breakpoint was configured, the log contains these two
mode-setup sequences:

```text
05{01}, 09(R09-1), 70{01}, 05{01}, 56{token}, 09(R09-1), 09(R09-5)
05{01}, 09(R09-1), 70{01}, 09(R09-5), 56{token}, 09(R09-1), 09(R09-5)
```

These orders are direct observations of the filtered outgoing writes.  Their
lifecycle labels come from the operator's capture context.

## Evidence boundary

The breakpoint filter records outgoing types `03`, `05`, and `07`.  It does
not capture incoming GET_FEATURE responses, RESET_RESPONSE, heatmap frames,
queue purge/flush operations, or a timestamp for every write.  Although a
breakpoint was configured for a reset-state entry, the expected entry message
does not appear in this raw log.  Therefore this capture alone does **not**
prove:

* that `0x05` or `0x70` has a six-byte logical payload;
* that report-09 bytes are copied from a GET_FEATURE response;
* that any particular packet difference is the reset-storm root cause;
* the complete Windows path from RESET_RESPONSE through resumed heat frames;
* the queue, synchronization, GPIO, ACPI, or power operations around recovery.

Those questions require additional debugger/static evidence.  Driver changes
must respect the explicit `txLen` and `content_len` boundaries above.
