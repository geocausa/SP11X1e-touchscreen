#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Regression-check directories of captured Surface G6 Heat frames.

The command is read-only. Captures remain outside the repository; only aggregate
statistics are printed. Parsing and contact acceptance mirror the Phase 55
kernel implementation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.decode_heat_frame import (
    MIN_CONTACT_PIXELS,
    WINDOWS_STRONG_MAX,
    accepted_contacts,
    connected_components,
    extract_heatmap,
    extract_report,
    modal_baseline,
    parse_sections,
)


def iter_frames(paths: list[Path]):
    seen: set[Path] = set()
    for supplied in paths:
        candidates = supplied.rglob("*.bin") if supplied.is_dir() else [supplied]
        for candidate in sorted(candidates):
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="+")
    parser.add_argument(
        "--expect-frames",
        type=int,
        help="fail unless exactly this many frame files are processed",
    )
    args = parser.parse_args()

    frame_count = 0
    contact_frames = 0
    idle_frames = 0
    palm_rejections = 0
    small_strong_contacts = 0
    weak_rejections = 0
    errors: list[tuple[Path, str]] = []
    baselines: Counter[int] = Counter()
    contact_counts: Counter[int] = Counter()
    largest_pixels = 0
    x_values: list[float] = []
    y_values: list[float] = []

    for path in iter_frames(args.paths):
        frame_count += 1
        try:
            report = extract_report(path.read_bytes())
            _, _, sections, _ = parse_sections(report)
            heat_sections = [section for section in sections if section.kind == 0x0100]
            if len(heat_sections) != 1:
                raise ValueError(f"expected one heat section, found {len(heat_sections)}")
            grid = extract_heatmap(heat_sections[0])
            baseline, _ = modal_baseline(grid)
            components = connected_components(grid, baseline)
            contacts, rejected = accepted_contacts(grid, baseline)
        except (OSError, ValueError) as error:
            errors.append((path, str(error)))
            continue

        baselines[baseline] += 1
        palm_rejections += rejected
        for component in components:
            if int(component["pixels"]) >= MIN_CONTACT_PIXELS:
                continue
            if int(component["peak_value"]) <= WINDOWS_STRONG_MAX:
                small_strong_contacts += 1
            else:
                weak_rejections += 1
        contact_counts[len(contacts)] += 1
        if contacts:
            contact_frames += 1
        else:
            idle_frames += 1
        for contact in contacts:
            largest_pixels = max(largest_pixels, int(contact["pixels"]))
            x_values.append(contact["x32767"])
            y_values.append(contact["y32767"])

    print(f"frames={frame_count} decoded={frame_count - len(errors)} errors={len(errors)}")
    print(
        f"contact_frames={contact_frames} idle_frames={idle_frames} "
        f"palm_rejections={palm_rejections} small_strong={small_strong_contacts} "
        f"weak_rejections={weak_rejections} max_contact_pixels={largest_pixels}"
    )
    print(
        "baselines="
        + ",".join(f"0x{value:02x}:{count}" for value, count in sorted(baselines.items()))
    )
    print(
        "contacts_per_frame="
        + ",".join(f"{value}:{count}" for value, count in sorted(contact_counts.items()))
    )
    if x_values:
        print(
            f"observed_contact_bounds=x:{min(x_values):.1f}..{max(x_values):.1f} "
            f"y:{min(y_values):.1f}..{max(y_values):.1f}"
        )

    for path, message in errors[:20]:
        print(f"ERROR {path}: {message}", file=sys.stderr)
    if len(errors) > 20:
        print(f"... {len(errors) - 20} additional errors", file=sys.stderr)

    if args.expect_frames is not None and frame_count != args.expect_frames:
        print(
            f"expected {args.expect_frames} frames, found {frame_count}",
            file=sys.stderr,
        )
        return 1
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
