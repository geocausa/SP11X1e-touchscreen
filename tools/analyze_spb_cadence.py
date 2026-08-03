#!/usr/bin/env python3
"""Measure HID-SPI cadence in a WPA- or tracerpt-exported SPB CSV."""

from __future__ import annotations

import argparse
import csv
import re
import statistics
from pathlib import Path


HEX_RE = re.compile(r"0x([0-9a-fA-F]+)")
HEADER_COMMAND = bytes.fromhex("eb001000ffffffff")
BODY_COMMAND = bytes.fromhex("eb001004ffffffff")
WINDOWS_TICKS_PER_US = 10


def iter_timed_buffers(path: Path):
    """Yield line, direction, FILETIME-style timestamp, and payload."""
    direction = None

    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        for line_number, row in enumerate(csv.reader(stream), 1):
            text = ",".join(row)
            if "IoSpbPayloadTdStart" in text:
                if "ToDevice" in text:
                    direction = "tx"
                elif "FromDevice" in text:
                    direction = "rx"
                else:
                    direction = None
                continue
            if "IoSpbPayloadTdBuffer" not in text or direction is None:
                continue

            matches = HEX_RE.findall(text)
            if not matches or len(row) <= 16:
                continue
            try:
                timestamp = int(row[16].strip())
                payload = bytes.fromhex(matches[-1])
            except ValueError:
                continue
            yield line_number, direction, timestamp, payload


def pair_responses(events):
    """Pair four SPB buffers into complete HID-SPI header/body responses."""
    responses = []
    index = 0
    while index + 3 < len(events):
        header_tx = events[index]
        header_rx = events[index + 1]
        body_tx = events[index + 2]
        body_rx = events[index + 3]
        header = header_rx[3]

        if (
            header_tx[1] == "tx"
            and header_tx[3] == HEADER_COMMAND
            and header_rx[1] == "rx"
            and len(header) == 4
            and header[0] & 0x0F == 3
            and header[3] == 0x5A
            and body_tx[1] == "tx"
            and body_tx[3] == BODY_COMMAND
            and body_rx[1] == "rx"
        ):
            words = int.from_bytes(header[1:3], "little") & 0x3FFF
            if len(body_rx[3]) == words * 4:
                responses.append(
                    {
                        "header_tx": header_tx[2],
                        "header_rx": header_rx[2],
                        "body_tx": body_tx[2],
                        "body_rx": body_rx[2],
                        "body": body_rx[3],
                    }
                )
                index += 4
                continue
        index += 1
    return responses


def heat_cadence_us(responses):
    """Return header/body and consecutive Heat response gaps in microseconds."""
    heat = [
        response
        for response in responses
        if len(response["body"]) >= 4
        and response["body"][0] == 1
        and response["body"][3] == 0x12
    ]
    header_body = [
        (response["body_tx"] - response["header_rx"])
        / WINDOWS_TICKS_PER_US
        for response in heat
    ]
    body_header = [
        (next_response["header_tx"] - response["body_rx"])
        / WINDOWS_TICKS_PER_US
        for response, next_response in zip(heat, heat[1:])
        if next_response["header_tx"] >= response["body_rx"]
    ]
    return heat, header_body, body_header


def summarize(values):
    """Return deterministic nearest-rank summary fields."""
    ordered = sorted(values)
    if not ordered:
        return None

    def percentile(fraction):
        return ordered[int((len(ordered) - 1) * fraction)]

    return {
        "count": len(ordered),
        "min": ordered[0],
        "p01": percentile(0.01),
        "median": statistics.median(ordered),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


def print_summary(label, values):
    summary = summarize(values)
    if summary is None:
        print(f"{label}: no samples")
        return
    print(
        f"{label}: n={summary['count']} min={summary['min']:.1f} us "
        f"p01={summary['p01']:.1f} us median={summary['median']:.1f} us "
        f"p99={summary['p99']:.1f} us max={summary['max']:.1f} us"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "csv", type=Path, help="WPA- or tracerpt-exported SPB CSV"
    )
    args = parser.parse_args()

    events = list(iter_timed_buffers(args.csv))
    responses = pair_responses(events)
    heat, header_body, body_header = heat_cadence_us(responses)
    print(f"Complete responses: {len(responses)}")
    print(f"Complete Heat responses: {len(heat)}")
    print_summary("Header RX to body TX", header_body)
    print_summary("Heat body RX to next Heat header TX", body_header)
    print(
        "Next-header gaps below 1 ms: "
        f"{sum(value < 1000 for value in body_header)}"
    )


if __name__ == "__main__":
    main()
