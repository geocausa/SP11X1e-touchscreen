# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

from hashlib import sha256
import unittest

from tools.windows_feedback import InitialFeedbackState, build_a1, build_a5_initial


class WindowsFeedbackTests(unittest.TestCase):
    def setUp(self):
        # Values captured on this exact SP11 during the unperturbed cold attach.
        self.state = InitialFeedbackState(1, 0, 0x0190, 0x0190)

    def test_a1_matches_complete_cold_kdnet_content(self):
        content = build_a1(self.state)
        self.assertEqual(len(content), 63)
        self.assertEqual(
            sha256(content).hexdigest(),
            "b2cae0b35eeb4fee62858ee05edfa2a626b48fe1ef14d38b383642d337504008",
        )

    def test_initial_a5_matches_complete_cold_kdnet_content(self):
        content = build_a5_initial(self.state)
        self.assertEqual(len(content), 63)
        self.assertEqual(
            sha256(content).hexdigest(),
            "f29901ec43a8efc1058e3242f59bdd8e627faf7e71f0fb1f6ca6df946f8a3a31",
        )

    def test_provider_values_are_range_checked(self):
        for state in (
            InitialFeedbackState(-1, 0, 0, 0),
            InitialFeedbackState(0, 2, 0, 0),
            InitialFeedbackState(0, 0, -1, 0),
            InitialFeedbackState(0, 0, 0, 0x10000),
        ):
            with self.assertRaises(ValueError):
                build_a1(state)


if __name__ == "__main__":
    unittest.main()
