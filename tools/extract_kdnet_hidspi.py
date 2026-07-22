#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Extract length-bounded HID-over-SPI writes from a WinDbg KDNET log.

The debugger often prints a reused transfer buffer.  This parser treats x5 as
the transmitted byte count and the HID-SPI content_len field as the logical
payload boundary.  Alignment bytes are reported separately and bytes beyond
x5 are never interpreted.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from typing import Iterator


REGISTERS = re.compile(
    r"x1=(?P<x1>[0-9a-f]+) .*?x4=(?P<x4>[0-9a-f`]+) "
    r"x5=(?P<x5>[0-9a-f]+) x6=(?P<x6>[0-9a-f`]+) "
    r"x7=(?P<x7>[0-9a-f]+)",
    re.IGNORECASE,
)
UPTIME = re.compile(r"System Uptime:\s*(.*)")
DUMP = re.compile(r"^[0-9a-f]{8}`[0-9a-f]{8}\s{2}(.+)$", re.IGNORECASE)
BYTE = re.compile(r"(?<![0-9a-f])[0-9a-f]{2}(?![0-9a-f])", re.IGNORECASE)
MODE_SETUP = re.compile(
    r"\[MODE-SETUP\].*?txLen=(?P<tx>[0-9a-f]+)\s+rxLen=(?P<rx>[0-9a-f]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Transfer:
    line: int
    uptime: str
    tx_len: int
    rx_len: int
    tx: bytes
    completion_line: int | None = None
    rx: bytes = b""

    @property
    def is_write(self) -> bool:
        return self.tx_len > 0 and self.rx_len == 0

    @property
    def is_hidspi_write(self) -> bool:
        return self.is_write and len(self.tx) >= 8 and self.tx[:4] == b"\xe2\x00\x20\x00"

    @property
    def is_header_read(self) -> bool:
        return self.tx[:4] == b"\xeb\x00\x10\x00" and self.rx_len == 4

    @property
    def is_body_read(self) -> bool:
        return self.tx[:4] == b"\xeb\x00\x10\x04" and self.rx_len >= 4

    @property
    def report_type(self) -> int | None:
        return self.tx[4] if self.is_hidspi_write else None

    @property
    def content_len(self) -> int | None:
        return int.from_bytes(self.tx[5:7], "little") if self.is_hidspi_write else None

    @property
    def content_id(self) -> int | None:
        return self.tx[7] if self.is_hidspi_write else None

    @property
    def content(self) -> bytes:
        if not self.is_hidspi_write:
            return b""
        length = self.content_len or 0
        return self.tx[8 : 8 + length]

    @property
    def padding(self) -> bytes:
        if not self.is_hidspi_write:
            return b""
        length = self.content_len or 0
        return self.tx[8 + length :]

    @property
    def response_class(self) -> int | None:
        return self.rx[0] if self.is_body_read and len(self.rx) >= 4 else None

    @property
    def response_content_len(self) -> int | None:
        if not self.is_body_read or len(self.rx) < 4:
            return None
        return int.from_bytes(self.rx[1:3], "little")

    @property
    def response_content_id(self) -> int | None:
        return self.rx[3] if self.is_body_read and len(self.rx) >= 4 else None

    @property
    def response_valid(self) -> bool:
        """Whether a completed body contains its declared logical content.

        A timed-out/instrumented transfer can complete with a header-like or
        repeated fill pattern in the body buffer.  Do not assign protocol
        meaning unless the four-byte body prefix and declared content fit in
        the bounded RX dump.
        """
        length = self.response_content_len
        return length is not None and 4 + length <= len(self.rx)


def _dump_bytes(line: str) -> bytes:
    match = DUMP.match(line)
    if not match:
        return b""
    # WinDbg separates the byte field from its ASCII rendering with 2+ spaces.
    field = re.split(r"\s{2,}", match.group(1), maxsplit=1)[0]
    return bytes(int(token, 16) for token in BYTE.findall(field))


def _parse_submissions(lines: list[str]) -> list[Transfer]:
    transfers: list[Transfer] = []
    index = 0
    while index < len(lines):
        mode_setup = MODE_SETUP.search(lines[index])
        if mode_setup:
            start = index
            tx_len = int(mode_setup.group("tx"), 16)
            rx_len = int(mode_setup.group("rx"), 16)
            data = bytearray()
            index += 1
            while index < len(lines):
                chunk = _dump_bytes(lines[index])
                if not chunk:
                    break
                data.extend(chunk)
                index += 1
            transfers.append(
                Transfer(start + 1, "unknown", tx_len, rx_len, bytes(data[:tx_len]))
            )
            continue

        if lines[index].strip() != "[MST-entry]":
            index += 1
            continue

        start = index
        index += 1
        uptime = "unknown"
        registers = None
        data = bytearray()
        while index < len(lines):
            line = lines[index]
            if line.strip() == "[MST-entry]" or line.startswith(" # Child-SP"):
                break
            match = UPTIME.search(line)
            if match:
                uptime = match.group(1).strip()
            match = REGISTERS.search(line)
            if match:
                registers = match.groupdict()
            data.extend(_dump_bytes(line))
            index += 1

        if registers is None:
            continue
        tx_len = int(registers["x5"], 16)
        rx_len = int(registers["x7"], 16)
        # x4 is the TX pointer; a zero x4 means there are no transmitted bytes.
        x4 = int(registers["x4"].replace("`", ""), 16)
        tx = bytes(data[:tx_len]) if x4 else b""
        transfers.append(Transfer(start + 1, uptime, tx_len, rx_len, tx))

    return transfers


def _parse_completions(lines: list[str]) -> dict[int, tuple[int, bytes]]:
    """Map each completion to the immediately preceding MST submission.

    Instrumentation can interrupt an MST block before its register dump is
    printed. Such a block cannot become a Transfer, but its completion must
    not shift the pairing of every later request.
    """
    completions: dict[int, tuple[int, bytes]] = {}
    submission_line: int | None = None
    index = 0

    while index < len(lines):
        if lines[index].strip() == "[MST-entry]":
            submission_line = index + 1
            index += 1
            continue
        if lines[index].strip() != "[CPL] CxClient--EvtSpbRequestCompletion":
            index += 1
            continue

        start = index
        data = bytearray()
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.startswith(" # Child-SP") or line.startswith("["):
                break
            data.extend(_dump_bytes(line))
            index += 1
        if submission_line is not None:
            completions[submission_line] = (start + 1, bytes(data))
            submission_line = None

    return completions


def parse_transfers(text: str) -> Iterator[Transfer]:
    lines = text.splitlines()
    transfers = _parse_submissions(lines)

    # The deep-session breakpoint relays one RX pointer/length to the next
    # CxClient completion. HidSpi serializes this request stream. Pair using
    # the actual MST boundary rather than list ordinal, because an interrupted
    # MST block may lack registers and be intentionally omitted above. Legacy
    # MODE-SETUP logs have neither marker and remain write-only evidence.
    if any(line.strip() == "[MST-entry]" for line in lines):
        completions = _parse_completions(lines)
        for index, transfer in enumerate(transfers):
            completion = completions.get(transfer.line)
            if completion is not None:
                line, data = completion
                transfers[index] = replace(
                    transfer,
                    completion_line=line,
                    rx=data[: transfer.rx_len],
                )

    yield from transfers


def transfer_record(transfer: Transfer) -> dict[str, object]:
    record: dict[str, object] = {
        "line": transfer.line,
        "uptime": transfer.uptime,
        "tx_len": transfer.tx_len,
        "rx_len": transfer.rx_len,
        "wire": transfer.tx.hex(" "),
        "completion_line": transfer.completion_line,
        "rx": transfer.rx.hex(" "),
    }
    if transfer.is_hidspi_write:
        record.update(
            report_type=transfer.report_type,
            content_id=transfer.content_id,
            content_len=transfer.content_len,
            content=transfer.content.hex(" "),
            alignment_padding=transfer.padding.hex(" "),
        )
    if transfer.is_body_read and transfer.response_class is not None:
        record.update(
            response_class=transfer.response_class,
            response_content_len=transfer.response_content_len,
            response_content_id=transfer.response_content_id,
            response_valid=transfer.response_valid,
        )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--all", action="store_true", help="include read and non-HID transfers")
    parser.add_argument("--json", action="store_true", help="emit JSON rather than JSON lines")
    args = parser.parse_args()

    transfers = list(parse_transfers(args.log.read_text(encoding="utf-8", errors="replace")))
    if not args.all:
        transfers = [item for item in transfers if item.is_hidspi_write]
    records = [transfer_record(item) for item in transfers]
    if args.json:
        print(json.dumps(records, indent=2))
    else:
        for record in records:
            print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
