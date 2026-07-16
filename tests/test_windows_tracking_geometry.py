# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import unittest
import struct

from tools.windows_tracking_geometry import (
    AssignmentScaleInputs,
    CandidateEdgeFlags,
    ExpandedCentroidBaselineInputs,
    ExpandedCentroidPolicy,
    ExpandedCentroidResult,
    OutputContact,
    ProfileRegion,
    TrackScalarBlendPolicy,
    TrackKinematics,
    WINDOWS_EDGE_SNAP_EPSILON,
    assignment_coordinate,
    assignment_pair_is_valid,
    blend_track_scalar,
    candidate_edge_flags,
    expanded_edge_centroid,
    merge_nearby_output_contacts,
    select_expanded_centroid_baseline,
    snap_far_edge_centroid,
    update_track_centroid_override_flag,
)


class WindowsTrackingGeometryTests(unittest.TestCase):
    def test_profile_region_uses_exact_inclusive_byte_rectangle(self):
        region = ProfileRegion.from_bytes(bytes((1, 10, 20, 30, 40)))
        self.assertTrue(region.contains(10.0, 40.0))
        self.assertTrue(region.contains(15.5, 35.25))
        self.assertFalse(region.contains(20.01, 35.0))
        self.assertFalse(ProfileRegion.from_bytes(b"\x00\x00\xff\x00\xff").contains(1, 1))
        with self.assertRaisesRegex(ValueError, "exactly five"):
            ProfileRegion.from_bytes(b"\x01\x02")

    def test_extracts_project_sensor_assignment_inputs(self):
        blob = bytearray(0x1000)
        blob[0:4] = b"PSDB"
        struct.pack_into("<HH", blob, 4, 4, 0x0C83)
        struct.pack_into("<I", blob, 0x18, len(blob))
        struct.pack_into("<HH", blob, 0x38 + 0x04, 46, 68)
        struct.pack_into("<HHh", blob, 0x3C, 46, 68, 0)
        struct.pack_into("<II", blob, 0x54, 18053, 27189)
        struct.pack_into("<I", blob, 0x64, 0)

        inputs = AssignmentScaleInputs.from_dll(bytes(blob), 0x0C83)
        self.assertEqual(
            inputs,
            AssignmentScaleInputs(27189, 18053, 68, 46, 0, 0, 0),
        )
        self.assertEqual(inputs.scales(), (4.0580596923828125, 4.011777877807617))

    def test_candidate_edge_flags_distinguish_edge_corner_and_margin(self):
        interior = candidate_edge_flags(
            min_x=3,
            max_x=4,
            min_y=5,
            max_y=6,
            centroid_x=3.5,
            centroid_y=5.5,
            x_node_count=12,
            y_node_count=20,
            edge_margin=1.0,
        )
        self.assertEqual(interior, CandidateEdgeFlags(0, False, False, False))

        edge = candidate_edge_flags(
            min_x=0,
            max_x=1,
            min_y=5,
            max_y=6,
            centroid_x=0.5,
            centroid_y=5.5,
            x_node_count=12,
            y_node_count=20,
            edge_margin=0.25,
        )
        self.assertEqual(edge, CandidateEdgeFlags(1, True, False, False))

        corner = candidate_edge_flags(
            min_x=0,
            max_x=1,
            min_y=0,
            max_y=1,
            centroid_x=0.5,
            centroid_y=0.5,
            x_node_count=12,
            y_node_count=20,
            edge_margin=0.0,
            context_active=True,
        )
        self.assertEqual(corner, CandidateEdgeFlags(5, True, True, True))

    def test_track_coordinates_are_direct_and_velocity_is_separate(self):
        track = TrackKinematics(10.25, 20.5)
        track.update(13.0, 18.0)

        self.assertEqual((track.x, track.y), (13.0, 18.0))
        self.assertEqual((track.velocity_x, track.velocity_y), (2.75, -2.5))
        self.assertEqual((track.predicted_x, track.predicted_y), (15.75, 15.5))
        self.assertEqual((track.min_x, track.min_y), (10.25, 18.0))
        self.assertEqual((track.max_x, track.max_y), (13.0, 20.5))
        self.assertEqual(track.age, 2)

    def test_track_updates_do_not_exponentially_blend_coordinates(self):
        track = TrackKinematics(100.0, 200.0)
        track.update(104.0, 208.0)
        track.update(105.0, 209.0)

        self.assertEqual((track.x, track.y), (105.0, 209.0))
        self.assertEqual((track.velocity_x, track.velocity_y), (1.0, 1.0))

    def test_track_scalar_blend_is_separate_and_motion_limited(self):
        policy = TrackScalarBlendPolicy(0.10000000149011612)
        self.assertEqual(
            blend_track_scalar(
                policy,
                previous_scalar=2.0,
                candidate_scalar=4.0,
                prior_class4_counter=0,
                motion_limited=True,
                velocity_x=0.0,
                velocity_y=0.0,
            ),
            4.0,
        )
        self.assertEqual(
            blend_track_scalar(
                policy,
                previous_scalar=2.0,
                candidate_scalar=4.0,
                prior_class4_counter=1,
                motion_limited=True,
                velocity_x=0.0,
                velocity_y=0.0,
            ),
            2.0,
        )
        self.assertEqual(
            blend_track_scalar(
                policy,
                previous_scalar=2.0,
                candidate_scalar=4.0,
                prior_class4_counter=1,
                motion_limited=False,
                velocity_x=0.0,
                velocity_y=0.0,
            ),
            2.200000047683716,
        )

    def test_extracts_track_scalar_alpha_from_project_blob(self):
        blob = bytearray(0x2000)
        blob[0:4] = b"PSDB"
        struct.pack_into("<HH", blob, 4, 4, 0x0C83)
        struct.pack_into("<I", blob, 0x18, len(blob))
        struct.pack_into("<f", blob, 0xDD0 + 0xEAC, 0.1)
        policy = TrackScalarBlendPolicy.from_dll(bytes(blob), 0x0C83)
        self.assertEqual(policy.base_alpha, 0.10000000149011612)

    def test_descriptor_scales_use_minus_one_for_zero_inset_layout(self):
        inputs = AssignmentScaleInputs(
            x_extent_hundredths=10000,
            y_extent_hundredths=20000,
            x_node_count=11,
            y_node_count=21,
            y_inset_count=0,
            y_inset_pitch=3,
            layout_mode=0,
        )
        x_scale, y_scale = inputs.scales()
        self.assertEqual(x_scale, 10.0)
        self.assertEqual(y_scale, 10.0)

    def test_descriptor_scales_remove_two_y_insets(self):
        inputs = AssignmentScaleInputs(
            x_extent_hundredths=12000,
            y_extent_hundredths=24000,
            x_node_count=12,
            y_node_count=30,
            y_inset_count=2,
            y_inset_pitch=2,
            layout_mode=1,
        )
        x_scale, y_scale = inputs.scales()
        self.assertEqual(x_scale, 10.0)
        self.assertAlmostEqual(
            y_scale, (240.0 - 8.0) / 26, places=6
        )

    def test_descriptor_rejects_impossible_denominators(self):
        with self.assertRaisesRegex(ValueError, "non-positive"):
            AssignmentScaleInputs(100, 100, 1, 1, 0, 0.0, 0).scales()

    def test_assignment_quantization_and_strict_radius(self):
        self.assertEqual(assignment_coordinate(2.49, 1.0), 2)
        self.assertEqual(assignment_coordinate(2.50, 1.0), 3)
        self.assertTrue(assignment_pair_is_valid(0, 0, 3, 3, 5.0))
        self.assertFalse(assignment_pair_is_valid(0, 0, 3, 4, 5.0))
        with self.assertRaisesRegex(ValueError, "non-negative"):
            assignment_coordinate(-1.0, 1.0)

    def test_far_edge_snap_has_exact_inclusive_epsilon(self):
        epsilon = WINDOWS_EDGE_SNAP_EPSILON
        self.assertEqual(snap_far_edge_centroid(7.0 + epsilon), 7.0)
        outside = 7.0 + epsilon * 1.01
        self.assertEqual(snap_far_edge_centroid(outside), outside)
        self.assertEqual(snap_far_edge_centroid(-2.5, 0.5), -3.0)

    def test_output_merge_uses_strict_squared_threshold_and_types_one_three(self):
        contacts = [
            OutputContact(0.0, 0.0, 1, 10, 2),
            OutputContact(3.0, 4.0, 3, 11, 4),
            OutputContact(1.0, 1.0, 2, 12, 6),
        ]

        self.assertEqual(merge_nearby_output_contacts(contacts, 25.0), set())
        self.assertEqual([contact.record_type for contact in contacts], [1, 3, 2])

        merged = merge_nearby_output_contacts(contacts, 36.0)
        self.assertEqual(merged, {2, 4})
        self.assertEqual([contact.group_id for contact in contacts], [10, 10, 12])
        self.assertEqual([contact.record_type for contact in contacts], [7, 3, 2])

    def test_output_merge_coalesces_identifier_chains_in_recorded_pair_order(self):
        contacts = [
            OutputContact(0.0, 0.0, 1, 1, 0),
            OutputContact(1.0, 0.0, 1, 2, 1),
            OutputContact(2.0, 0.0, 1, 3, 2),
            OutputContact(20.0, 0.0, 1, 2, 3),
        ]

        merged = merge_nearby_output_contacts(contacts, 4.0)
        self.assertEqual(merged, {0, 1, 2})
        self.assertEqual([contact.group_id for contact in contacts], [1, 1, 1, 1])
        self.assertEqual([contact.record_type for contact in contacts], [7, 7, 7, 1])

    def test_expanded_centroid_baseline_branch_order(self):
        common = dict(
            reference_baseline=1.0,
            profile_baseline_c858=2.0,
            alternate_baseline_c844=3.0,
            frame_maximum_exceeded=False,
            profile_predicate=False,
            processor_flag_198c8=False,
            output_flag_97=False,
        )
        self.assertEqual(
            select_expanded_centroid_baseline(ExpandedCentroidBaselineInputs(**common)),
            1.0,
        )
        self.assertEqual(
            select_expanded_centroid_baseline(
                ExpandedCentroidBaselineInputs(**{**common, "profile_predicate": True})
            ),
            2.0,
        )
        self.assertEqual(
            select_expanded_centroid_baseline(
                ExpandedCentroidBaselineInputs(**{**common, "output_flag_97": True})
            ),
            3.0,
        )
        self.assertEqual(
            select_expanded_centroid_baseline(
                ExpandedCentroidBaselineInputs(
                    **{
                        **common,
                        "frame_maximum_exceeded": True,
                        "profile_predicate": True,
                        "processor_flag_198c8": True,
                    }
                )
            ),
            1.0,
        )

    def test_track_centroid_override_flag_is_sticky_with_exact_boundaries(self):
        common = dict(
            current=False,
            candidate_flag_b1=True,
            updated_age=2,
            maximum_point_count=4,
            frame_maximum_exceeded=False,
        )
        self.assertTrue(update_track_centroid_override_flag(**common))
        self.assertFalse(
            update_track_centroid_override_flag(**{**common, "updated_age": 1})
        )
        self.assertFalse(
            update_track_centroid_override_flag(
                **{**common, "maximum_point_count": 5}
            )
        )
        self.assertFalse(
            update_track_centroid_override_flag(
                **{**common, "frame_maximum_exceeded": True}
            )
        )
        self.assertTrue(
            update_track_centroid_override_flag(
                **{
                    **common,
                    "current": True,
                    "candidate_flag_b1": False,
                    "frame_maximum_exceeded": True,
                }
            )
        )

    def test_extracts_exact_expanded_centroid_psdb_policy(self):
        blob = bytearray(0x2000)
        blob[0:4] = b"PSDB"
        struct.pack_into("<HH", blob, 4, 4, 0x0C83)
        struct.pack_into("<I", blob, 0x18, len(blob))
        struct.pack_into("<H", blob, 0xB84 + 0x08, 20)
        struct.pack_into("<H", blob, 0xB84 + 0x10, 171)
        struct.pack_into("<H", blob, 0xB84 + 0x18, 180)

        policy = ExpandedCentroidPolicy.from_dll(bytes(blob), 0x0C83)
        self.assertEqual(policy.admission_multiplier, 0.19999998807907104)
        self.assertEqual(
            (policy.normal_baseline_index, policy.high_frame_baseline_index),
            (171, 180),
        )
        self.assertFalse(policy.processor_override_enabled)

        normal = policy.baseline_inputs(
            frame_maximum_exceeded=False,
            profile_predicate=False,
            output_flag_97=False,
        )
        self.assertEqual(normal.reference_baseline, 0.02031940221786499)
        self.assertEqual(normal.profile_baseline_c858, 0.004776895046234131)
        self.assertEqual(normal.alternate_baseline_c844, 0.015878677368164062)

        high = policy.baseline_inputs(
            frame_maximum_exceeded=True,
            profile_predicate=True,
            output_flag_97=True,
        )
        self.assertEqual(high.reference_baseline, 0.0003362298011779785)
        self.assertEqual(
            select_expanded_centroid_baseline(high), high.reference_baseline
        )

    def test_expanded_centroid_admits_only_orthogonal_one_cell_halo(self):
        labels = (
            (0, 0, 0, 0, 0),
            (0, 0, 0, 0, 0),
            (0, 0, 1, 0, 0),
            (0, 0, 0, 0, 0),
            (0, 0, 0, 0, 0),
        )
        # Component cell uses level 2 (10.0), empty cells level 1 (2.0).
        level_indices = tuple(tuple(2 if value else 1 for value in row) for row in labels)
        result = expanded_edge_centroid(
            label_grid=labels,
            level_index_grid=level_indices,
            label_owner=(0, 7),
            levels=(0.0, 2.0, 10.0),
            component_owner=7,
            min_x=2,
            min_y=2,
            max_x=2,
            max_y=2,
            candidate_level_index=2,
            admission_multiplier=0.5,
            baseline=1.0,
            clamp_expanded_window=False,
        )
        self.assertEqual(
            result.admitted_halo_cells,
            ((1, 2), (2, 1), (2, 3), (3, 2)),
        )
        self.assertEqual((result.x, result.y), (2.0, 2.0))
        self.assertEqual(result.weight, 13.0)

    def test_expanded_centroid_uses_member_signal_for_halo_gate(self):
        labels = ((0, 0, 0), (0, 1, 0), (0, 0, 0))
        level_indices = ((1, 1, 1), (1, 2, 1), (1, 1, 1))
        result = expanded_edge_centroid(
            label_grid=labels,
            level_index_grid=level_indices,
            label_owner=(0, 1),
            levels=(0.0, 5.0, 6.0),
            component_owner=1,
            min_x=1,
            min_y=1,
            max_x=1,
            max_y=1,
            candidate_level_index=2,
            admission_multiplier=1.0,
            baseline=0.0,
            clamp_expanded_window=False,
        )
        self.assertEqual(result.admitted_halo_cells, ())  # strict 6.0 < 6.0 fails
        self.assertEqual((result.x, result.y), (1.0, 1.0))

    def test_expanded_centroid_rounds_halo_level_before_strict_gate(self):
        labels = ((0, 0, 0), (0, 1, 0), (0, 0, 0))
        level_indices = ((0, 0, 0), (0, 1, 0), (0, 0, 0))
        result = expanded_edge_centroid(
            label_grid=labels,
            level_index_grid=level_indices,
            label_owner=(0, 1),
            levels=(0.0, 1.0 + 1.0e-8),
            component_owner=1,
            min_x=1,
            min_y=1,
            max_x=1,
            max_y=1,
            candidate_level_index=1,
            admission_multiplier=1.0,
            baseline=0.0,
            clamp_expanded_window=False,
        )
        # Both operands round to 1.0f; Windows' strict comparison is false.
        self.assertEqual(result.admitted_halo_cells, ())

    def test_expanded_centroid_clamps_far_edge_and_snaps(self):
        labels = ((0, 0, 0), (0, 0, 1), (0, 0, 0))
        level_indices = ((0, 0, 0), (0, 0, 1), (0, 0, 0))
        result = expanded_edge_centroid(
            label_grid=labels,
            level_index_grid=level_indices,
            label_owner=(0, 4),
            levels=(0.0, 10.0),
            component_owner=4,
            min_x=2,
            min_y=1,
            max_x=2,
            max_y=1,
            candidate_level_index=1,
            admission_multiplier=2.0,
            baseline=0.0,
            clamp_expanded_window=True,
        )
        self.assertEqual(result, ExpandedCentroidResult(2.0, 1.0, (), 10.0))

    def test_expanded_centroid_keeps_signed_member_excess(self):
        labels = ((0, 0, 0, 0), (0, 1, 1, 0), (0, 0, 0, 0))
        level_indices = ((1, 1, 1, 1), (1, 0, 2, 1), (1, 1, 1, 1))
        result = expanded_edge_centroid(
            label_grid=labels,
            level_index_grid=level_indices,
            label_owner=(0, 1),
            levels=(0.0, 1.0, 3.0),
            component_owner=1,
            min_x=1,
            min_y=1,
            max_x=2,
            max_y=1,
            candidate_level_index=2,
            admission_multiplier=100.0,
            baseline=1.0,
            clamp_expanded_window=False,
        )
        self.assertEqual(result.weight, 1.0)
        self.assertEqual((result.x, result.y), (3.0, 1.0))

    def test_expanded_centroid_preserves_dll_edge_accumulation_order(self):
        levels = (
            10000000.0, 0.01, 1000.0, 1000.0,
            1000.0, 0.1, 0.01, 1000.0,
            0.1, 0.01, 100.0, 1.0,
            1.0, 0.01, 1.0, 100.0,
        )
        result = expanded_edge_centroid(
            label_grid=tuple(tuple(1 for _ in range(4)) for _ in range(4)),
            level_index_grid=tuple(
                tuple(row * 4 + column for column in range(4))
                for row in range(4)
            ),
            label_owner=(0, 1),
            levels=levels,
            component_owner=1,
            min_x=0,
            min_y=0,
            max_x=3,
            max_y=3,
            candidate_level_index=0,
            admission_multiplier=1.0e30,
            baseline=0.0,
            clamp_expanded_window=True,
        )
        self.assertEqual(result.weight, 10004203.0)
        self.assertEqual(result.x, 0.0008501576958224177)
        self.assertEqual(result.y, 0.00025073063443414867)


if __name__ == "__main__":
    unittest.main()
