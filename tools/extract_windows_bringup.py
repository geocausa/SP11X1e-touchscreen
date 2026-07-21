#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Build an ownership-aware Windows HID-over-SPI lifecycle ledger.

The KDNET stream contains traffic from independent HID collection owners.  A
chronological list is therefore evidence of interleaving, not a startup script.
This tool preserves wire order while labeling the owner implied by the report
descriptor and splits the stream at actual RESET_RESPONSE boundaries.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

try:
    from tools.extract_kdnet_hidspi import Transfer, parse_transfers
except ModuleNotFoundError:  # Direct execution from the tools directory.
    from extract_kdnet_hidspi import Transfer, parse_transfers


OUTPUT_TYPE_NAMES = {
    1: "DEVICE_DESCRIPTOR",
    2: "REPORT_DESCRIPTOR",
    3: "SET_FEATURE",
    4: "GET_FEATURE",
    5: "OUTPUT_REPORT",
    6: "GET_INPUT_REPORT",
    7: "COMMAND_CONTENT",
}

INPUT_CLASS_NAMES = {
    1: "DATA",
    3: "RESET_RESPONSE",
    4: "COMMAND_RESPONSE",
    5: "GET_FEATURE_RESPONSE",
    7: "DEVICE_DESCRIPTOR_RESPONSE",
    8: "REPORT_DESCRIPTOR_RESPONSE",
    9: "SET_FEATURE_RESPONSE",
    10: "OUTPUT_REPORT_RESPONSE",
    11: "GET_INPUT_REPORT_RESPONSE",
}


def command_owner(report_type: int, content_id: int) -> str:
    """Return the narrowest owner supported by descriptor/static evidence."""
    if report_type in (1, 2):
        return "hidspi-core"
    if report_type == 7 and content_id == 1:
        return "power-lifecycle"
    if content_id in (0x05, 0x06, 0x09):
        return "heat-feedback-collection"
    if content_id in (0x54, 0x55, 0x56, 0x6E, 0x6F, 0x70, 0x73):
        return "device-config-collection"
    if content_id in (0x60, 0x65):
        return "cfu-collection"
    return "unresolved"


def response_owner(response_class: int, content_id: int) -> str:
    if response_class in (3, 7, 8):
        return "hidspi-core"
    if response_class == 4 and content_id == 1:
        return "power-lifecycle"
    # A response has the same report ID as its initiating collection request.
    return command_owner(0, content_id)


@dataclass(frozen=True)
class LedgerEvent:
    line: int
    uptime: str
    direction: str
    operation: str
    owner: str
    content_id: int
    content_len: int
    content: bytes

    def record(self) -> dict[str, object]:
        return {
            "line": self.line,
            "uptime": self.uptime,
            "direction": self.direction,
            "operation": self.operation,
            "owner": self.owner,
            "content_id": self.content_id,
            "content_len": self.content_len,
            "content": self.content.hex(" "),
        }


@dataclass(frozen=True)
class LifecycleEpisode:
    index: int
    events: tuple[LedgerEvent, ...]

    @property
    def kind(self) -> str:
        writes = {(event.operation, event.content_id) for event in self.events
                  if event.direction == "host-to-panel"}
        has_reset = any(event.operation == "RESET_RESPONSE" for event in self.events)
        if ("COMMAND_CONTENT", 1) in writes and not has_reset:
            return "power-teardown"
        if has_reset and ("REPORT_DESCRIPTOR", 0) in writes:
            return "cold-enumeration"
        if has_reset and ("DEVICE_DESCRIPTOR", 0) in writes:
            return "restart-or-recovery"
        return "unclassified"

    def record(self) -> dict[str, object]:
        return {
            "index": self.index,
            "kind": self.kind,
            "events": [event.record() for event in self.events],
        }


def relevant_events(transfers: Iterable[Transfer]) -> list[LedgerEvent]:
    events: list[LedgerEvent] = []
    for transfer in transfers:
        if transfer.is_hidspi_write:
            report_type = transfer.report_type
            content_id = transfer.content_id
            assert report_type is not None and content_id is not None
            events.append(
                LedgerEvent(
                    transfer.line,
                    transfer.uptime,
                    "host-to-panel",
                    OUTPUT_TYPE_NAMES.get(report_type, f"OUTPUT_TYPE_{report_type}"),
                    command_owner(report_type, content_id),
                    content_id,
                    transfer.content_len or 0,
                    transfer.content,
                )
            )
            continue

        if not transfer.is_body_read or not transfer.response_valid:
            continue
        response_class = transfer.response_class
        content_id = transfer.response_content_id
        content_len = transfer.response_content_len
        assert response_class is not None and content_id is not None
        assert content_len is not None
        # Streaming DATA is intentionally omitted: this is a control ledger.
        if response_class == 1:
            continue
        events.append(
            LedgerEvent(
                transfer.line,
                transfer.uptime,
                "panel-to-host",
                INPUT_CLASS_NAMES.get(response_class,
                                      f"INPUT_CLASS_{response_class}"),
                response_owner(response_class, content_id),
                content_id,
                content_len,
                transfer.rx[4 : 4 + content_len],
            )
        )
    return events


def lifecycle_episodes(events: Iterable[LedgerEvent]) -> list[LifecycleEpisode]:
    episodes: list[list[LedgerEvent]] = []
    current: list[LedgerEvent] = []
    for event in events:
        if event.operation == "RESET_RESPONSE" and current:
            episodes.append(current)
            current = []
        current.append(event)
    if current:
        episodes.append(current)
    return [LifecycleEpisode(index + 1, tuple(items))
            for index, items in enumerate(episodes)]


def markdown(episodes: Iterable[LifecycleEpisode]) -> str:
    lines = [
        "| episode | kind | uptime | direction | operation | id | len | owner | content |",
        "|---:|---|---|---|---|---:|---:|---|---|",
    ]
    for episode in episodes:
        for event in episode.events:
            content = event.content.hex(" ")
            if len(content) > 71:
                content = content[:68] + "..."
            lines.append(
                f"| {episode.index} | {episode.kind} | {event.uptime} | "
                f"{event.direction} | {event.operation} | `0x{event.content_id:02x}` | "
                f"{event.content_len} | {event.owner} | `{content}` |"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()

    transfers = parse_transfers(args.log.read_text(encoding="utf-8", errors="replace"))
    episodes = lifecycle_episodes(relevant_events(transfers))
    if args.markdown:
        print(markdown(episodes))
    else:
        print(json.dumps([episode.record() for episode in episodes], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
