import unittest

from lightcycle.domain.pool import (
    claude_health_score, github_health_score, health_image_state, health_score,
    maintenance_health_score, pool_health_score, releases_behind,
)


class TestPoolHealthScore(unittest.TestCase):
    def test_every_pool_state(self):
        expected = {
            "starting": 1, "stopping": 1, "draining": 1,
            "start-timed-out": 4, "stop-timed-out": 4, "stopped": 4,
        }
        for state, score in expected.items():
            self.assertEqual(pool_health_score(state, "healthy", None, 5), score, state)

    def test_transition_wins_over_a_stalled_tick(self):
        self.assertEqual(pool_health_score("starting", "stalled", None, 5), 1)

    def test_running_healthy_or_unread_is_zero(self):
        self.assertEqual(pool_health_score("running", "healthy", 1, 5), 0)
        self.assertEqual(pool_health_score("running", None, None, 5), 0)

    def test_running_stalled_is_four(self):
        self.assertEqual(pool_health_score("running", "stalled", None, 5), 4)

    def test_lagging_bands_have_inclusive_bounds(self):
        bands = {5: 1, 10: 1, 11: 2, 20: 2, 21: 3, 90: 3}
        for median, score in bands.items():
            self.assertEqual(pool_health_score("running", "lagging", median, 5), score, median)

    def test_lagging_without_a_median_scores_one(self):
        self.assertEqual(pool_health_score("running", "lagging", None, 5), 1)


class TestClaudeAndUpgradeScores(unittest.TestCase):
    def test_claude(self):
        self.assertEqual(claude_health_score(False), 0)
        self.assertEqual(claude_health_score(True), 4)

    def test_nothing_pending_is_zero(self):
        self.assertEqual(maintenance_health_score(False, None, False, False, False), 0)

    def test_each_single_signal_is_one(self):
        self.assertEqual(maintenance_health_score(True, 1, False, False, False), 1)
        self.assertEqual(maintenance_health_score(False, None, True, False, False), 1)
        self.assertEqual(maintenance_health_score(False, None, False, True, False), 1)
        self.assertEqual(maintenance_health_score(False, None, False, False, True), 1)

    def test_all_four_signals_give_three(self):
        self.assertEqual(maintenance_health_score(True, 1, True, True, True), 3)

    def test_three_releases_behind_adds_one(self):
        self.assertEqual(maintenance_health_score(True, 3, False, False, False), 2)

    def test_four_signals_plus_staleness_stay_at_three(self):
        self.assertEqual(maintenance_health_score(True, 4, True, True, True), 3)

    def test_unknown_staleness_adds_nothing(self):
        self.assertEqual(maintenance_health_score(True, None, False, False, False), 1)

    def test_releases_behind_counts_patch_distance(self):
        self.assertEqual(releases_behind("0.7.98", "0.7.102"), 4)
        self.assertEqual(releases_behind("0.7.102", "0.7.102"), 0)
        self.assertEqual(releases_behind("0.7.103", "0.7.102"), 0)

    def test_releases_behind_across_minor_counts_as_stale(self):
        self.assertEqual(releases_behind("0.7.99", "0.8.0"), 3)

    def test_releases_behind_unknown_when_either_version_missing_or_malformed(self):
        self.assertIsNone(releases_behind(None, "0.7.102"))
        self.assertIsNone(releases_behind("0.7.98", None))
        self.assertIsNone(releases_behind("dev", "0.7.102"))


class TestGithubHealthScore(unittest.TestCase):
    def test_band_edges(self):
        edges = {
            100: 0, 81: 0, 80: 1, 61: 1, 60: 2, 41: 2, 40: 3, 21: 3, 20: 4, 0: 4,
        }
        for pct, score in edges.items():
            self.assertEqual(github_health_score(pct, 100), score, pct)

    def test_percent_is_integer_division_like_the_footer(self):
        self.assertEqual(github_health_score(809, 1000), 1)
        self.assertEqual(github_health_score(810, 1000), 0)

    def test_unknown_budget_is_zero(self):
        self.assertEqual(github_health_score(None, None), 0)
        self.assertEqual(github_health_score(5, 0), 0)

    def test_remaining_above_limit_clamps_to_zero(self):
        self.assertEqual(github_health_score(150, 100), 0)


class TestWorstWins(unittest.TestCase):
    def test_worst_signal_wins(self):
        self.assertEqual(health_score(0, 4, 2, 1), 4)
        self.assertEqual(health_score(0, 0, 0, 0), 0)
        self.assertEqual(health_score(0, 0, 3, 1), 3)

    def test_maintenance_alone_reaches_three(self):
        self.assertEqual(health_score(0, 0, 0, 3), 3)

    def test_stalled_pool_still_gives_four_over_maintenance(self):
        self.assertEqual(health_score(pool_health_score("running", "stalled", None, 5), 0, 0, 3), 4)


class TestHealthImageState(unittest.TestCase):
    def test_busy_only_at_score_zero(self):
        self.assertEqual(health_image_state(0, True), "busy")
        self.assertEqual(health_image_state(1, True), "1")
        self.assertEqual(health_image_state(0, False), "0")
        self.assertEqual(health_image_state(4, True), "4")
