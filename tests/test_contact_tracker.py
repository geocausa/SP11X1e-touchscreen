# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

import unittest
import random

from tools.track_heat_contacts import (
    ContactTracker,
    Measurement,
    Track,
    kernel_style_matches,
    minimum_cost_matches,
)


def point(x: int, y: int) -> Measurement:
    return Measurement(x=x, y=y, pixels=8, strength=100)


class ContactTrackerTests(unittest.TestCase):
    def test_kernel_hungarian_matches_dp_oracle(self):
        randomizer = random.Random(0x58)
        for _ in range(200):
            tracks = [
                Track(slot=index, raw_x=randomizer.randrange(32768), raw_y=randomizer.randrange(32768), output_x=0, output_y=0)
                for index in range(randomizer.randrange(1, 7))
            ]
            measurements = [
                point(randomizer.randrange(32768), randomizer.randrange(32768))
                for _ in range(randomizer.randrange(1, 7))
            ]
            expected = minimum_cost_matches(tracks, measurements, 8192)
            actual = kernel_style_matches(tracks, measurements, 8192)
            self.assertEqual(len(actual), len(expected))
            expected_cost = sum(
                round(
                    ((tracks[i].predicted_x - measurements[j].x) ** 2 +
                     (tracks[i].predicted_y - measurements[j].y) ** 2) ** 0.5
                )
                for i, j in expected
            )
            actual_cost = sum(
                round(
                    ((tracks[i].predicted_x - measurements[j].x) ** 2 +
                     (tracks[i].predicted_y - measurements[j].y) ** 2) ** 0.5
                )
                for i, j in actual
            )
            self.assertEqual(actual_cost, expected_cost)

    def test_measurement_reordering_does_not_swap_slots(self):
        tracker = ContactTracker()
        first = tracker.update([point(2000, 4000), point(20000, 4000)])
        second = tracker.update([point(20100, 4000), point(2100, 4000)])
        self.assertEqual([(item.slot, item.raw_x) for item in first], [(0, 2000), (1, 20000)])
        self.assertEqual([(item.slot, item.raw_x) for item in second], [(0, 2100), (1, 20100)])

    def test_prediction_preserves_identity_through_crossing(self):
        tracker = ContactTracker(match_gate=6000)
        tracker.update([point(10000, 5000), point(14000, 5000)])
        tracker.update([point(11500, 5000), point(12500, 5000)])
        crossed = tracker.update([point(11000, 5000), point(13000, 5000)])
        self.assertEqual([(item.slot, item.raw_x) for item in crossed], [(0, 13000), (1, 11000)])

    def test_far_jump_closes_old_track_only_after_hold(self):
        tracker = ContactTracker(match_gate=1000, hold_frames=2)
        tracker.update([point(1000, 1000)])
        result = tracker.update([point(10000, 10000)])
        self.assertEqual([(item.slot, item.held) for item in result], [(0, True), (1, False)])
        tracker.update([])
        tracker.update([])
        result = tracker.update([])
        self.assertEqual(result, [])

    def test_short_dropout_retains_slot_and_position(self):
        tracker = ContactTracker(hold_frames=2)
        first = tracker.update([point(5000, 6000)])[0]
        held = tracker.update([])[0]
        recovered = tracker.update([point(5100, 6000)])[0]
        self.assertEqual(held.slot, first.slot)
        self.assertEqual((held.x, held.y), (first.x, first.y))
        self.assertTrue(held.held)
        self.assertEqual(recovered.slot, first.slot)
        self.assertFalse(recovered.held)

    def test_stationary_jitter_is_smoothed_but_fast_motion_is_not(self):
        tracker = ContactTracker()
        tracker.update([point(1000, 1000)])
        jitter = tracker.update([point(1040, 1000)])[0]
        self.assertEqual(jitter.x, 1010)
        fast = tracker.update([point(3000, 1000)])[0]
        self.assertEqual(fast.x, 3000)


if __name__ == "__main__":
    unittest.main()
