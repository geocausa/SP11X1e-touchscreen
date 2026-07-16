#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Extract and evaluate the project classifier from TouchPenProcessor.

The Microsoft DLL is supplied by the operator and is never copied into this
repository.  This tool implements the data path recovered from project 0x0c83;
it does not classify Heat frames by itself because several upstream feature
generators still require an exact offline port.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import struct


PSDB_MAGIC = b"PSDB"
PSDB_VERSION = 4
PROJECT_CONFIG_OFFSET = 0xDD0
CLASSIFIER_OFFSET = 0x134
CLASSIFIER_STRIDE = 0x1D0
CLASS_COUNT = 4
FEATURE_COUNT = 10
TRANSFORM_ROW_STRIDE = 0x2C
MODEL_BIAS_OFFSET = 0x190
MODEL_MEANS_OFFSET = 0x198
MODEL_DECISIONS_OFFSET = 0x1C0
MAX_POINT_COUNTS_OFFSET = 0x870
BASE_FEATURE_MASK_OFFSET = 0x10C
STATE_FEATURE_MASK_OFFSET = 0x11C
RUNTIME_EXPONENT_OFFSET = 0xE76
PRIMARY_SCORE3_PENALTY_OFFSET = 0x8D0
SINGLE_GROUP_SCORE3_PENALTY_OFFSET = 0x8D4
# DAT_180044508 is the little-endian double 0x401921fb54442d18: 2*pi.
# An earlier decompiler transcription treated its decimal text as a large
# integer, which did not affect class winners but invalidated absolute scores.
WINDOWS_LOG_BASE = math.tau
DISABLED_SCORE = -9999.0
FIXED_SHIFT = 12
FIXED_ONE = 1 << FIXED_SHIFT


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def f32(data: bytes, offset: int) -> float:
    return struct.unpack_from("<f", data, offset)[0]


def find_project_blob(data: bytes, project_id: int) -> tuple[int, int]:
    """Return the unique validated PSDB blob offset and serialized length."""
    matches: list[tuple[int, int]] = []
    offset = 0
    while True:
        offset = data.find(PSDB_MAGIC, offset)
        if offset < 0:
            break
        if offset + 0x20 <= len(data):
            version = u16(data, offset + 4)
            found_project = u16(data, offset + 6)
            serialized_length = u32(data, offset + 0x18)
            if (
                version == PSDB_VERSION
                and found_project == project_id
                and serialized_length >= PROJECT_CONFIG_OFFSET
                and offset + serialized_length <= len(data)
            ):
                matches.append((offset, serialized_length))
        offset += 1
    if not matches:
        raise ValueError(f"no valid version-4 PSDB for project {project_id:#06x}")
    if len(matches) != 1:
        raise ValueError(
            f"found {len(matches)} valid PSDB blobs for project {project_id:#06x}"
        )
    return matches[0]


@dataclass(frozen=True)
class StatisticalModel:
    transform: tuple[tuple[float, ...], ...]
    means: tuple[float, ...]
    bias: float
    decisions: tuple[float, float]
    max_points: int


@dataclass(frozen=True)
class ProjectClassifier:
    project_id: int
    psdb_offset: int
    psdb_length: int
    feature_masks: tuple[int, ...]
    state_feature_masks: tuple[int, ...]
    runtime_offset: float
    primary_score3_penalty: float
    single_group_score3_penalty: float
    models: tuple[StatisticalModel, ...]

    @classmethod
    def from_dll(cls, data: bytes, project_id: int) -> "ProjectClassifier":
        blob_offset, blob_length = find_project_blob(data, project_id)
        config = blob_offset + PROJECT_CONFIG_OFFSET
        required = max(
            PROJECT_CONFIG_OFFSET
            + CLASSIFIER_OFFSET
            + (CLASS_COUNT - 1) * CLASSIFIER_STRIDE
            + MODEL_DECISIONS_OFFSET
            + 8,
            PROJECT_CONFIG_OFFSET + MAX_POINT_COUNTS_OFFSET + CLASS_COUNT * 4,
            PROJECT_CONFIG_OFFSET + STATE_FEATURE_MASK_OFFSET + FEATURE_COUNT,
            PROJECT_CONFIG_OFFSET + RUNTIME_EXPONENT_OFFSET + 2,
        )
        if required > blob_length:
            raise ValueError("PSDB is too short for the classifier model blocks")

        max_points = struct.unpack_from(
            f"<{CLASS_COUNT}I", data, config + MAX_POINT_COUNTS_OFFSET
        )
        models: list[StatisticalModel] = []
        for class_index in range(CLASS_COUNT):
            base = config + CLASSIFIER_OFFSET + class_index * CLASSIFIER_STRIDE
            rows: list[tuple[float, ...]] = []
            for row in range(FEATURE_COUNT):
                values = [0.0] * FEATURE_COUNT
                for column in range(row, FEATURE_COUNT):
                    values[column] = f32(
                        data,
                        base
                        + row * TRANSFORM_ROW_STRIDE
                        + (column - row) * 4,
                    )
                rows.append(tuple(values))
            means = struct.unpack_from(
                f"<{FEATURE_COUNT}f", data, base + MODEL_MEANS_OFFSET
            )
            decisions = struct.unpack_from("<2f", data, base + MODEL_DECISIONS_OFFSET)
            model = StatisticalModel(
                transform=tuple(rows),
                means=tuple(means),
                bias=f32(data, base + MODEL_BIAS_OFFSET),
                decisions=tuple(decisions),
                max_points=max_points[class_index],
            )
            flat_values = [value for row in model.transform for value in row]
            if not all(
                math.isfinite(value)
                for value in (*flat_values, *model.means, model.bias, *model.decisions)
            ):
                raise ValueError(f"class {class_index} contains a non-finite model value")
            models.append(model)

        exponent = u16(data, config + RUNTIME_EXPONENT_OFFSET)
        runtime_offset = math.log(0.25) - exponent * math.log(WINDOWS_LOG_BASE) * 0.5
        return cls(
            project_id=project_id,
            psdb_offset=blob_offset,
            psdb_length=blob_length,
            feature_masks=tuple(
                data[config + BASE_FEATURE_MASK_OFFSET + index]
                for index in range(FEATURE_COUNT)
            ),
            state_feature_masks=tuple(
                data[config + STATE_FEATURE_MASK_OFFSET + index]
                for index in range(FEATURE_COUNT)
            ),
            runtime_offset=runtime_offset,
            primary_score3_penalty=f32(
                data, config + PRIMARY_SCORE3_PENALTY_OFFSET
            ),
            single_group_score3_penalty=f32(
                data, config + SINGLE_GROUP_SCORE3_PENALTY_OFFSET
            ),
            models=tuple(models),
        )

    def apply_basic_score_postprocessing(
        self,
        scores: tuple[float, ...],
        *,
        primary_flag: bool,
        secondary_count: int,
    ) -> tuple[float, ...]:
        """Mirror FUN_180049638's unconditional class-three adjustment.

        The remainder of FUN_180049638 contains context/region overrides and
        is deliberately outside this basic helper.
        """
        if len(scores) != CLASS_COUNT:
            raise ValueError(f"expected {CLASS_COUNT} scores, got {len(scores)}")
        adjusted = list(scores)
        if primary_flag:
            adjusted[3] -= self.primary_score3_penalty
        elif secondary_count == 1:
            adjusted[3] -= self.single_group_score3_penalty
        return tuple(adjusted)

    def scores(
        self,
        features: tuple[float, ...],
        decision_index: int,
        state_mask: int = 0,
    ) -> tuple[float, ...]:
        """Mirror FUN_1800406a8 for one of its two decision-state branches."""
        if len(features) != FEATURE_COUNT:
            raise ValueError(f"expected {FEATURE_COUNT} features, got {len(features)}")
        if decision_index not in (0, 1):
            raise ValueError("decision index must be 0 or 1")
        if not all(math.isfinite(value) for value in features):
            raise ValueError("features must all be finite")

        masked = tuple(
            bool(base | (state & state_mask))
            for base, state in zip(self.feature_masks, self.state_feature_masks)
        )
        # Windows uses 100.0 as the unavailable halo-ratio sentinel and masks
        # the tenth feature before evaluating the statistical model.
        masked = (*masked[:9], masked[9] or features[9] == 100.0)

        scores: list[float] = []
        for model in self.models:
            if features[0] > model.max_points:
                scores.append(DISABLED_SCORE)
                continue
            residual = tuple(
                0.0 if masked[index] else features[index] - model.means[index]
                for index in range(FEATURE_COUNT)
            )
            transformed = tuple(
                sum(
                    residual[column] * model.transform[row][column]
                    for column in range(row, FEATURE_COUNT)
                )
                for row in range(FEATURE_COUNT)
            )
            distance = sum(value * value for value in transformed)
            score = (
                model.decisions[decision_index]
                - model.bias * 0.5
                + self.runtime_offset
                - distance * 0.5
            )
            scores.append(score)
        return tuple(scores)

    def fixed_scores(
        self,
        features: tuple[float, ...],
        decision_index: int,
        state_mask: int = 0,
    ) -> tuple[int, ...]:
        """Evaluate the model in the Q20.12 form used by the kernel port.

        The common runtime offset is omitted because it cannot change the
        winning class. Returned values are Q40.24 score numerators.
        """
        if len(features) != FEATURE_COUNT:
            raise ValueError(f"expected {FEATURE_COUNT} features, got {len(features)}")
        if decision_index not in (0, 1):
            raise ValueError("decision index must be 0 or 1")
        masked = tuple(
            bool(base | (state & state_mask))
            for base, state in zip(self.feature_masks, self.state_feature_masks)
        )
        masked = (*masked[:9], masked[9] or features[9] == 100.0)
        feature_q = tuple(round(value * FIXED_ONE) for value in features)

        scores: list[int] = []
        for model in self.models:
            if features[0] > model.max_points:
                scores.append(round(DISABLED_SCORE * FIXED_ONE * FIXED_ONE))
                continue
            means_q = tuple(round(value * FIXED_ONE) for value in model.means)
            residual_q = tuple(
                0 if masked[index] else feature_q[index] - means_q[index]
                for index in range(FEATURE_COUNT)
            )
            transformed_q = []
            for row in range(FEATURE_COUNT):
                accumulator = sum(
                    residual_q[column]
                    * round(model.transform[row][column] * FIXED_ONE)
                    for column in range(row, FEATURE_COUNT)
                )
                transformed_q.append(accumulator >> FIXED_SHIFT)
            distance_q24 = sum(value * value for value in transformed_q)
            offset_q12 = round(
                (model.decisions[decision_index] - model.bias * 0.5) * FIXED_ONE
            )
            scores.append(offset_q12 * FIXED_ONE - distance_q24 // 2)
        return tuple(scores)

    def summary(self) -> dict[str, object]:
        return {
            "project_id": f"0x{self.project_id:04x}",
            "psdb_offset": self.psdb_offset,
            "psdb_length": self.psdb_length,
            "feature_masks": self.feature_masks,
            "state_feature_masks": self.state_feature_masks,
            "runtime_offset": self.runtime_offset,
            "primary_score3_penalty": self.primary_score3_penalty,
            "single_group_score3_penalty": self.single_group_score3_penalty,
            "models": [
                {
                    "max_points": model.max_points,
                    "bias": model.bias,
                    "means": model.means,
                    "decisions": model.decisions,
                    "nonzero_transform_values": sum(
                        value != 0.0 for row in model.transform for value in row
                    ),
                }
                for model in self.models
            ],
        }


def parse_project_id(value: str) -> int:
    parsed = int(value, 0)
    if not 0 <= parsed <= 0xFFFF:
        raise argparse.ArgumentTypeError("project ID must fit in 16 bits")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dll", type=Path)
    parser.add_argument("--project", type=parse_project_id, default=0x0C83)
    parser.add_argument("--features", type=float, nargs=FEATURE_COUNT)
    parser.add_argument("--state-mask", type=parse_project_id, default=0)
    args = parser.parse_args()

    classifier = ProjectClassifier.from_dll(args.dll.read_bytes(), args.project)
    output = classifier.summary()
    if args.features is not None:
        features = tuple(args.features)
        output["features"] = features
        output["scores_decision_0"] = classifier.scores(
            features, 0, state_mask=args.state_mask
        )
        output["scores_decision_1"] = classifier.scores(
            features, 1, state_mask=args.state_mask
        )
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
