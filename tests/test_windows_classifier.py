# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import math
import struct
import unittest

from tools.extract_windows_classifier import (
    BASE_FEATURE_MASK_OFFSET,
    CLASSIFIER_OFFSET,
    CLASSIFIER_STRIDE,
    DISABLED_SCORE,
    FEATURE_COUNT,
    MAX_POINT_COUNTS_OFFSET,
    MODEL_BIAS_OFFSET,
    MODEL_DECISIONS_OFFSET,
    MODEL_MEANS_OFFSET,
    PROJECT_CONFIG_OFFSET,
    ProjectClassifier,
    RUNTIME_EXPONENT_OFFSET,
    STATE_FEATURE_MASK_OFFSET,
    TRANSFORM_ROW_STRIDE,
    find_project_blob,
)


def make_test_dll(project_id=0x0C83):
    blob_length = 0x2000
    prefix = b"not a PE requirement for the bounded parser\x00"
    blob = bytearray(blob_length)
    blob[0:4] = b"PSDB"
    struct.pack_into("<HH", blob, 4, 4, project_id)
    struct.pack_into("<I", blob, 0x18, blob_length)
    config = PROJECT_CONFIG_OFFSET
    struct.pack_into("<4I", blob, config + MAX_POINT_COUNTS_OFFSET, 5, 10, 15, 20)
    struct.pack_into("<H", blob, config + RUNTIME_EXPONENT_OFFSET, 0)
    for class_index in range(4):
        base = config + CLASSIFIER_OFFSET + class_index * CLASSIFIER_STRIDE
        for row in range(FEATURE_COUNT):
            struct.pack_into("<f", blob, base + row * TRANSFORM_ROW_STRIDE, 1.0)
        struct.pack_into(
            f"<{FEATURE_COUNT}f", blob, base + MODEL_MEANS_OFFSET, *([0.0] * 10)
        )
        struct.pack_into("<f", blob, base + MODEL_BIAS_OFFSET, class_index * 2.0)
        struct.pack_into("<2f", blob, base + MODEL_DECISIONS_OFFSET, 1.0, 3.0)
    return prefix + bytes(blob), len(prefix)


class WindowsClassifierTests(unittest.TestCase):
    def test_finds_project_blob_and_rejects_wrong_project(self):
        data, expected_offset = make_test_dll()
        self.assertEqual(find_project_blob(data, 0x0C83), (expected_offset, 0x2000))
        with self.assertRaisesRegex(ValueError, "no valid"):
            find_project_blob(data, 0x0C80)

    def test_rejects_blob_too_short_for_classifier(self):
        data, blob_offset = make_test_dll()
        mutable = bytearray(data[: blob_offset + 0x1000])
        struct.pack_into("<I", mutable, blob_offset + 0x18, 0x1000)
        with self.assertRaisesRegex(ValueError, "too short"):
            ProjectClassifier.from_dll(bytes(mutable), 0x0C83)

    def test_extracts_models_and_scores_identity_transform(self):
        data, expected_offset = make_test_dll()
        classifier = ProjectClassifier.from_dll(data, 0x0C83)
        self.assertEqual(classifier.psdb_offset, expected_offset)
        self.assertEqual(tuple(model.max_points for model in classifier.models), (5, 10, 15, 20))
        features = (2.0,) + (1.0,) * 9
        distance = 2.0**2 + 9.0
        expected = tuple(
            1.0 - class_index - math.log(4.0) - distance * 0.5
            for class_index in range(4)
        )
        self.assertEqual(classifier.scores(features, 0), expected)
        self.assertEqual(
            classifier.scores(features, 1), tuple(value + 2.0 for value in expected)
        )

    def test_point_limit_and_feature_masks(self):
        data, _ = make_test_dll()
        mutable = bytearray(data)
        blob = data.find(b"PSDB")
        config = blob + PROJECT_CONFIG_OFFSET
        mutable[config + BASE_FEATURE_MASK_OFFSET + 1] = 1
        mutable[config + STATE_FEATURE_MASK_OFFSET + 2] = 2
        classifier = ProjectClassifier.from_dll(bytes(mutable), 0x0C83)
        features = (6.0,) + (5.0,) * 8 + (100.0,)
        scores = classifier.scores(features, 0, state_mask=2)
        self.assertEqual(scores[0], DISABLED_SCORE)
        self.assertNotEqual(scores[1], DISABLED_SCORE)
        # Features 1, 2 and the unavailable-halo sentinel are all masked.
        expected_distance = 6.0**2 + 6.0 * 5.0**2
        expected_class1 = 1.0 - 1.0 - math.log(4.0) - expected_distance * 0.5
        self.assertEqual(scores[1], expected_class1)


if __name__ == "__main__":
    unittest.main()
