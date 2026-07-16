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
    ContextMetadataState,
    HeatCalibrationPolicy,
    MIN_CONTACT_PIXELS,
    WINDOWS_NSR_CUTOFF,
    WINDOWS_STRONG_MAX,
    accepted_contacts,
    connected_components,
    extract_context_sources,
    extract_heatmap,
    extract_nsr_bins,
    extract_report,
    local_peak_counts,
    modal_baseline,
    parse_metadata_records,
    parse_sections,
    windows_classifier_features,
)
from tools.extract_windows_classifier import ProjectClassifier
from tools.extract_windows_lifecycle import BaseClassHistory, ProjectLifecycle, UNCLASSIFIED
from tools.windows_tracking_geometry import (
    AssignmentScaleInputs,
    assignment_coordinate,
    kernel_q24_assignment_coordinate,
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
    parser.add_argument(
        "--classifier-dll",
        type=Path,
        help="verify floating-point and Q20.12 class winners against this DLL",
    )
    parser.add_argument(
        "--base-lifecycle",
        action="store_true",
        help=(
            "run the recovered context-neutral score-gate ordering; this is "
            "not the final Windows lifecycle/output decision"
        ),
    )
    args = parser.parse_args()

    classifier = None
    assignment_scales = None
    lifecycle = None
    calibration_policy = None
    if args.classifier_dll is not None:
        try:
            dll = args.classifier_dll.read_bytes()
            classifier = ProjectClassifier.from_dll(dll, 0x0C83)
            assignment_scales = AssignmentScaleInputs.from_dll(
                dll, 0x0C83
            ).scales()
            calibration_policy = HeatCalibrationPolicy.from_dll(dll, 0x0C83)
            if args.base_lifecycle:
                lifecycle = ProjectLifecycle.from_dll(dll, 0x0C83)
        except (OSError, ValueError) as error:
            parser.error(f"cannot load classifier: {error}")
    elif args.base_lifecycle:
        parser.error("--base-lifecycle requires --classifier-dll")

    frame_count = 0
    contact_frames = 0
    idle_frames = 0
    palm_rejections = 0
    small_strong_contacts = 0
    weak_rejections = 0
    nsr_metadata_frames = 0
    nsr_rejections = 0
    nsr_value_max = 0
    nsr_values: Counter[int] = Counter()
    context_metadata_frames = 0
    context_b771_nonzero = 0
    context_b7ea_nonzero = 0
    type94_frames = 0
    context_state = ContextMetadataState()
    heat_encodings: Counter[tuple[int, int]] = Counter()
    errors: list[tuple[Path, str]] = []
    baselines: Counter[int] = Counter()
    contact_counts: Counter[int] = Counter()
    largest_pixels = 0
    x_values: list[float] = []
    y_values: list[float] = []
    axis_ratios: list[float] = []
    normalized_spreads: list[float] = []
    classifier_classes: Counter[int] = Counter()
    classifier_mismatches = 0
    peak_count_distribution: Counter[tuple[int, int]] = Counter()
    assignment_q24_mismatches = 0
    base_history: BaseClassHistory | None = None
    base_selected_classes: Counter[int] = Counter()
    base_gate_counts: Counter[str] = Counter()
    base_accepted = 0
    base_rejected = 0
    base_sequence_age = 0
    base_onset_delays: list[int] = []
    base_sequence_reported = False

    for path in iter_frames(args.paths):
        frame_count += 1
        try:
            report = extract_report(path.read_bytes())
            _, _, sections, _ = parse_sections(report)
            heat_sections = [section for section in sections if section.kind == 0x0100]
            if len(heat_sections) != 1:
                raise ValueError(f"expected one heat section, found {len(heat_sections)}")
            metadata_sections = [
                section for section in sections if section.kind == 0xFF00
            ]
            if len(metadata_sections) > 1:
                raise ValueError(
                    f"expected at most one metadata section, found {len(metadata_sections)}"
                )
            nsr_bins = (
                extract_nsr_bins(metadata_sections[0]) if metadata_sections else None
            )
            context_sources = None
            frame_has_type94 = False
            if metadata_sections:
                metadata_records = parse_metadata_records(metadata_sections[0])
                frame_has_type94 = any(
                    record.kind == 0x94 for record in metadata_records
                )
                context_sources = extract_context_sources(
                    metadata_sections[0], context_state
                )
            grid = extract_heatmap(heat_sections[0])
            baseline, _ = modal_baseline(grid)
            components = connected_components(grid, baseline)
            unfiltered_contacts, _ = accepted_contacts(grid, baseline)
            contacts, rejected = accepted_contacts(grid, baseline, nsr_bins=nsr_bins)
        except (OSError, ValueError) as error:
            errors.append((path, str(error)))
            continue

        baselines[baseline] += 1
        heat_encodings[(heat_sections[0].mode, heat_sections[0].header_value)] += 1
        if context_sources is not None:
            context_state = context_sources.next_state
            context_metadata_frames += 1
            type94_frames += frame_has_type94
            context_b771_nonzero += context_sources.frame_b771 != 0
            context_b7ea_nonzero += context_sources.frame_b7ea != 0
        palm_rejections += rejected
        if nsr_bins is not None:
            nsr_metadata_frames += 1
            nsr_rejections += max(0, len(unfiltered_contacts) - len(contacts))
            nsr_values.update(nsr_bins)
            if nsr_bins:
                nsr_value_max = max(nsr_value_max, max(nsr_bins))
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
        if lifecycle is not None and len(contacts) != 1:
            base_history = None
            base_sequence_age = 0
            base_sequence_reported = False
        for contact in contacts:
            largest_pixels = max(largest_pixels, int(contact["pixels"]))
            x_values.append(contact["x32767"])
            y_values.append(contact["y32767"])
            axis_ratios.append(contact["axis_ratio"])
            normalized_spreads.append(contact["normalized_spread"])
            if assignment_scales is not None:
                strength = int(contact["strength"])
                weighted_x = round(float(contact["col"]) * strength)
                weighted_y = round(float(contact["row"]) * strength)
                floating_assignment = (
                    assignment_coordinate(contact["col"], assignment_scales[0]),
                    assignment_coordinate(contact["row"], assignment_scales[1]),
                )
                fixed_assignment = (
                    kernel_q24_assignment_coordinate(
                        weighted_x, strength, assignment_scales[0]
                    ),
                    kernel_q24_assignment_coordinate(
                        weighted_y, strength, assignment_scales[1]
                    ),
                )
                assignment_q24_mismatches += (
                    floating_assignment != fixed_assignment
                )
            if classifier is not None:
                features = windows_classifier_features(grid, contact)
                floating = classifier.scores(features, 0)
                peaks = local_peak_counts(grid, contact)
                lifecycle_scores = classifier.apply_basic_score_postprocessing(
                    floating,
                    primary_flag=peaks[0] == 1,
                    secondary_count=peaks[1],
                )
                peak_count_distribution[peaks] += 1
                fixed = classifier.fixed_scores(features, 0)
                floating_class = max(range(len(floating)), key=floating.__getitem__)
                fixed_class = max(range(len(fixed)), key=fixed.__getitem__)
                classifier_classes[fixed_class] += 1
                classifier_mismatches += floating_class != fixed_class
                if lifecycle is not None and len(contacts) == 1:
                    if base_history is None:
                        base_history = BaseClassHistory(lifecycle)
                    base_sequence_age += 1
                    decision = base_history.update(
                        lifecycle_scores, point_count=int(contact["pixels"])
                    )
                    base_selected_classes[decision.selected_class] += 1
                    base_gate_counts[decision.gate] += 1
                    if decision.accepted:
                        base_accepted += 1
                    else:
                        base_rejected += 1
                    if (
                        not base_sequence_reported
                        and decision.selected_class in (0, 2)
                    ):
                        base_onset_delays.append(base_sequence_age)
                        base_sequence_reported = True

    print(f"frames={frame_count} decoded={frame_count - len(errors)} errors={len(errors)}")
    print(
        f"contact_frames={contact_frames} idle_frames={idle_frames} "
        f"palm_rejections={palm_rejections} small_strong={small_strong_contacts} "
        f"weak_rejections={weak_rejections} max_contact_pixels={largest_pixels}"
    )
    print(
        f"nsr_metadata_frames={nsr_metadata_frames} "
        f"nsr_rejections={nsr_rejections} nsr_cutoff={WINDOWS_NSR_CUTOFF} "
        f"nsr_value_max={nsr_value_max} "
        "nsr_values="
        + ",".join(f"{value}:{count}" for value, count in sorted(nsr_values.items()))
    )
    print(
        f"context_metadata_frames={context_metadata_frames} "
        f"type94_frames={type94_frames} "
        f"b771_nonzero={context_b771_nonzero} "
        f"b7ea_nonzero={context_b7ea_nonzero} "
        f"b7ea_final={context_state.type94_subtype0}"
    )
    calibration = "not_loaded"
    if calibration_policy is not None:
        calibration = (
            f"enabled={int(calibration_policy.enabled)},"
            f"gain={calibration_policy.gain:g},"
            f"offset={calibration_policy.offset:g}"
        )
    print(
        "heat_encodings="
        + ",".join(
            f"mode{mode}/width{width}:{count}"
            for (mode, width), count in sorted(heat_encodings.items())
        )
        + f" project_u16_calibration={calibration}"
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
        print(
            "windows_geometry_bounds="
            f"axis_ratio:{min(axis_ratios):.6f}..{max(axis_ratios):.6f} "
            f"normalized_spread:{min(normalized_spreads):.6f}.."
            f"{max(normalized_spreads):.6f}"
        )
    if classifier is not None:
        print(
            "classifier_classes="
            + ",".join(
                f"{value}:{count}"
                for value, count in sorted(classifier_classes.items())
            )
            + f" fixed_point_mismatches={classifier_mismatches}"
            + f" assignment_q24_mismatches={assignment_q24_mismatches}"
        )
        print(
            "local_peaks="
            + ",".join(
                f"{raw}/{strong}:{count}"
                for (raw, strong), count in sorted(peak_count_distribution.items())
            )
        )
    if lifecycle is not None:
        delay_counts = Counter(base_onset_delays)
        print(
            "base_lifecycle_selected="
            + ",".join(
                f"{value}:{count}"
                for value, count in sorted(base_selected_classes.items())
            )
            + " gates="
            + ",".join(
                f"{value}:{count}" for value, count in sorted(base_gate_counts.items())
            )
            + f" accepted={base_accepted} rejected={base_rejected} "
            + f"unclassified={base_selected_classes[UNCLASSIFIED]} "
            + "finger_onset_delay="
            + ",".join(
                f"{value}:{count}" for value, count in sorted(delay_counts.items())
            )
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
    return 1 if errors or classifier_mismatches or assignment_q24_mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
