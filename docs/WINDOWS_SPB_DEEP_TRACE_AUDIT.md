# Windows SPB deep-trace audit

## Result

An older Windows ETW capture contains the complete
`Microsoft-Windows-SPB-ClassExtension` payload stream for this `MSHW0485`
panel.  It independently proves that report `0x09` is not sent once per Heat
frame.

During a 33.336-second trace, Windows received 1,381 complete raw Heat report
`0x12` bodies and transmitted report `0x09` exactly twice: one A1 posture
record and one A5 V06 record, adjacent during device re-attachment.  There
were 95 Heat bodies before those writes and 1,286 after them.  No report
`0x09` write occurs in the continuing Heat stream.

This agrees with the static call graph in
[WINDOWS_FEEDBACK_ATTACH_RE.md](WINDOWS_FEEDBACK_ATTACH_RE.md): attach/reset
forces the initial A1/A5 pair, while the post-frame feedback drain is
pending-gated and normally transmits nothing.

It directly disproves the local Claude note claiming that Windows sends live
finger coordinates to the panel in report `0x09` on every frame.  The guessed
Claude-v9 contact-record layout must not be imported into the driver.

## Evidence identity

The artifacts remain on the read-only private evidence disk and are not
redistributed:

```text
e16ccb799f0299848599a3422775306302ebdfb888838c4abe6935e2a7e188b4  sp11-touch-deep_000001.etl
0209583a33f180bf7cd76d17c90ba16da3a37a93921253c2e667af40ebcb1514  sp11-touch-deep.csv
```

The CSV is the WPA export of the ETL's SPB class-extension provider.  The
repository's read-only parser reproduces the buffer and report counts:

```text
python3 tools/analyze_spb_etw_csv.py /path/to/sp11-touch-deep.csv
```

Relevant parser results are:

```text
Class-1 report 0x12, 3636 bytes: 1381
Set-output report 0x09, 63 bytes: 2
```

## Exact feedback bodies

The two logical 63-byte contents are:

```text
13718293999b3e7156d6c1fbb9bffb24feff9060dfce9aa50f7c89fdead1ce55  A1
7a32974c648ddef4b0c10ca14d3c90675bd12aaf3ba55e3497d8c6dc6a03c6d3  A5
```

Their non-zero offsets are:

```text
A1: 0:8e 1:a1 2:01 4:90 5:01 40:1a 41:03
A5: 0:8e 1:a5 3:02 39:1a 40:03 46:40
```

The value at A1 offsets 40-41 and A5 offsets 39-40 is FastHostId `0x031a`.
Later July KDNET captures from the same machine contain `0x0190` in these
fields.  That cross-session change independently confirms that FastHostId is
provider/persistent state rather than a panel constant or contact coordinate.

## Restart chronology and ownership

The trace begins with an already-running Heat stream.  At 6.113 seconds the
host sends the teardown-side report `0x56` value containing six `0xff` bytes,
then at 6.122 seconds sends standard HID-SPI `SET_POWER(OFF)`.  A new child
enumeration begins with an empty panel `RESET_RESPONSE` at 10.251 seconds.

The 17 host-to-panel `E2 00 20 00` writes in the trace reduce to this order:

```text
SET_FEATURE 56 = ff ff ff ff ff ff 00
SET_POWER OFF
DEVICE_DESCRIPTOR request
REPORT_DESCRIPTOR request
GET_FEATURE 60
OUTPUT 65 x4
GET_FEATURE 70
SET_FEATURE 70 = 01
SET_FEATURE 56 = bc e6 4a 2e 86 78 00
GET_FEATURE 06
OUTPUT 09 A1
OUTPUT 09 A5
SET_FEATURE 05 = 01
GET_FEATURE 73
```

The four report-`0x65` bodies and the `0x60` query are the CFU collection's
inventory exchange.  Reports `0x70` and `0x56` belong to device configuration;
`0x06`, `0x09`, and `0x05` belong to Heat/feedback activation.  The trace
therefore captures independent collection owners interleaving on one
serialized bus.  Its ordering differs from the later unperturbed cold KDNET
capture without contradicting it.

The A1/A5 pair occurs 109.0 ms after the `RESET_RESPONSE` and inside the long
Heat hiatus around re-enumeration.  The previous Heat body is 4.730 seconds
earlier and the next is 7.177 seconds later.  This is attach/restart traffic,
not frame cadence.

## Evidence boundary

This trace proves:

- Windows does not normally transmit report `0x09` for every raw Heat frame;
- one A1/A5 pair is emitted during this attach/restart;
- the A1/A5 bodies carry dynamic provider state;
- CFU, device-configuration, and Heat owners can interleave differently from
  a cold capture.

It does not prove:

- that A1 or A5 can be omitted from cold attach;
- which minimum A1/A5 fields the panel requires for stable Heat operation;
- the natural panel-reset trigger;
- that this restart chronology is a synchronous recipe suitable for Linux.

Those limits preserve the Phase 84 design: provider-built A1/A5 feedback is
appropriate in an isolated attach-parity path, but per-frame guessed feedback
and flattened replay of all collection traffic are not.
