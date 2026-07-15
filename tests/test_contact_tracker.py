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
        third = tracker.update([point(20200, 4000), point(2200, 4000)])

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(
            [(item.slot, item.raw_x) for item in third],
            [(0, 2200), (1, 20200)],
        )

    def test_prediction_preserves_identity_through_crossing(self):
        tracker = ContactTracker(match_gate=6000)
        tracker.update([point(10000, 5000), point(14000, 5000)])
        tracker.update([point(11500, 5000), point(12500, 5000)])
        crossed = tracker.update([point(11000, 5000), point(13000, 5000)])
        self.assertEqual([(item.slot, item.raw_x) for item in crossed], [(0, 13000), (1, 11000)])

    def test_far_jump_does_not_emit_retained_old_track(self):
        tracker = ContactTracker(match_gate=1000, hold_frames=2)
        tracker.update([point(1000, 1000)])
        result = tracker.update([point(10000, 10000)])
        self.assertEqual(result, [])
        result = tracker.update([point(10000, 10000)])
        self.assertEqual(result, [])
        result = tracker.update([point(10000, 10000)])
        self.assertEqual(
            [(item.slot, item.raw_x, item.held) for item in result],
            [(1, 10000, False)],
        )
        tracker.update([])
        tracker.update([])
        result = tracker.update([])
        self.assertEqual(result, [])

    def test_short_dropout_retains_slot_without_emitting_ghost(self):
        tracker = ContactTracker(hold_frames=2)
        tracker.update([point(5000, 6000)])
        tracker.update([point(5000, 6000)])
        first = tracker.update([point(5000, 6000)])[0]
        held = tracker.update([])
        recovered = tracker.update([point(5100, 6000)])[0]

        self.assertEqual(held, [])
        self.assertEqual(recovered.slot, first.slot)
        self.assertFalse(recovered.held)

    def test_stationary_jitter_is_smoothed_but_fast_motion_is_not(self):
        tracker = ContactTracker()
        tracker.update([point(1000, 1000)])
        tracker.update([point(1000, 1000)])
        tracker.update([point(1000, 1000)])
        jitter = tracker.update([point(1040, 1000)])[0]
        self.assertEqual(jitter.x, 1010)
        fast = tracker.update([point(3000, 1000)])[0]
        self.assertEqual(fast.x, 3000)

    def test_two_frame_candidate_is_never_emitted(self):
        tracker = ContactTracker(confirm_frames=3)

        self.assertEqual(tracker.update([point(12000, 8000)]), [])
        self.assertEqual(tracker.update([point(12000, 8000)]), [])
        self.assertEqual(tracker.update([]), [])

    def test_nearby_weak_split_requires_long_history(self):
        tracker = ContactTracker()
        primary = point(12000, 8000)
        weak_split = Measurement(x=12600, y=8200, pixels=3, strength=40)

        tracker.update([primary])
        tracker.update([primary])
        self.assertEqual(len(tracker.update([primary])), 1)

        for _ in range(7):
            reported = tracker.update([primary, weak_split])
            self.assertEqual(len(reported), 1)
        reported = tracker.update([primary, weak_split])
        self.assertEqual(len(reported), 2)

    def test_far_second_finger_uses_normal_confirmation(self):
        tracker = ContactTracker()
        primary = point(4000, 6000)
        second = point(22000, 16000)

        tracker.update([primary])
        tracker.update([primary])
        tracker.update([primary])
        self.assertEqual(len(tracker.update([primary, second])), 1)
        self.assertEqual(len(tracker.update([primary, second])), 1)
        self.assertEqual(len(tracker.update([primary, second])), 2)

    def test_confirmed_track_does_not_flicker_on_weak_shape(self):
        tracker = ContactTracker()
        strong = point(10000, 10000)
        weak = Measurement(x=10020, y=10010, pixels=2, strength=30)

        tracker.update([strong])
        tracker.update([strong])
        tracker.update([strong])
        reported = tracker.update([weak])
        self.assertEqual(len(reported), 1)
        self.assertEqual(reported[0].slot, 0)


if __name__ == "__main__":
    unittest.main()
