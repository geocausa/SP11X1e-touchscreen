# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import unittest

from tools.windows_tracking_geometry import (
    AssignmentScaleInputs,
    CandidateEdgeFlags,
    OutputContact,
    TrackKinematics,
    WINDOWS_DESCRIPTOR_UNIT,
    WINDOWS_EDGE_SNAP_EPSILON,
    assignment_coordinate,
    assignment_pair_is_valid,
    candidate_edge_flags,
    merge_nearby_output_contacts,
    snap_far_edge_centroid,
)


class WindowsTrackingGeometryTests(unittest.TestCase):
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

    def test_descriptor_scales_use_minus_one_for_zero_inset_layout(self):
        inputs = AssignmentScaleInputs(
            x_extent_hundredths=10000,
            y_extent_hundredths=20000,
            x_node_count=11,
            y_node_count=21,
            y_inset_count=0,
            y_inset_pitch=3.5,
            layout_mode=0,
        )
        x_scale, y_scale = inputs.scales()
        self.assertAlmostEqual(x_scale, 10000 * WINDOWS_DESCRIPTOR_UNIT / 10)
        self.assertAlmostEqual(y_scale, 20000 * WINDOWS_DESCRIPTOR_UNIT / 20)

    def test_descriptor_scales_remove_two_y_insets(self):
        inputs = AssignmentScaleInputs(
            x_extent_hundredths=12000,
            y_extent_hundredths=24000,
            x_node_count=12,
            y_node_count=30,
            y_inset_count=2,
            y_inset_pitch=1.25,
            layout_mode=1,
        )
        x_scale, y_scale = inputs.scales()
        self.assertAlmostEqual(x_scale, 12000 * WINDOWS_DESCRIPTOR_UNIT / 12)
        self.assertAlmostEqual(
            y_scale, (24000 * WINDOWS_DESCRIPTOR_UNIT - 5.0) / 26
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


if __name__ == "__main__":
    unittest.main()
