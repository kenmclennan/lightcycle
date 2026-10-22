import unittest

from lightcycle.domain.pool import (
    TickTiming, tick_age_text, tick_health, tick_timing_from_state, tick_timing_recorded,
    tick_timing_started,
)

NOW = 10000.0
ARGS = dict(poll_seconds=5, window_seconds=300, share_percent=50, stall_seconds=120)


def _timing(durations, finished_ago=5.0, pid=1):
    ticks = tuple((NOW - finished_ago - i, d) for i, d in enumerate(durations))
    return TickTiming(pid, NOW - finished_ago, ticks)


def _health(timing, now=NOW):
    return tick_health(timing, now, **ARGS)


class TestTickHealth(unittest.TestCase):
    def test_all_fast_ticks_are_healthy(self):
        self.assertEqual(_health(_timing([1, 1, 1, 1])).level, "healthy")

    def test_exactly_the_share_threshold_is_healthy(self):
        self.assertEqual(_health(_timing([9, 9, 1, 1])).level, "healthy")

    def test_just_over_the_share_threshold_is_lagging(self):
        h = _health(_timing([9, 9, 9, 1]))
        self.assertEqual(h.level, "lagging")
        self.assertEqual(h.median_seconds, 9)

    def test_a_single_slow_tick_among_ten_stays_healthy(self):
        self.assertEqual(_health(_timing([30] + [1] * 9)).level, "healthy")

    def test_a_tick_of_exactly_poll_seconds_is_not_slow(self):
        self.assertEqual(_health(_timing([5.0, 5.0, 5.0])).level, "healthy")
        self.assertEqual(_health(_timing([5.1, 5.1, 5.1])).level, "lagging")

    def test_stalled_past_the_bound_and_not_at_it(self):
        self.assertEqual(_health(_timing([1], finished_ago=121)).level, "stalled")
        self.assertEqual(_health(_timing([1], finished_ago=120)).level, "healthy")

    def test_stalled_wins_over_lagging(self):
        t = _timing([9, 9, 9, 1], finished_ago=200)
        self.assertEqual(_health(t).level, "stalled")

    def test_empty_window_is_healthy_with_no_median(self):
        h = _health(TickTiming(1, NOW - 5, ()))
        self.assertEqual((h.level, h.median_seconds), ("healthy", None))

    def test_ticks_older_than_the_window_are_excluded(self):
        old = tuple((NOW - 1000 - i, 30) for i in range(5))
        h = _health(TickTiming(1, NOW - 5, old + ((NOW - 5, 1),)))
        self.assertEqual((h.level, h.median_seconds), ("healthy", 1))

    def test_median_rounds_half_up(self):
        self.assertEqual(_health(_timing([2, 3])).median_seconds, 3)
        self.assertEqual(_health(_timing([9.0, 9.4, 9.6])).median_seconds, 9)

    def test_age_is_whole_seconds_and_never_negative(self):
        self.assertEqual(_health(_timing([1], finished_ago=45.9)).age_seconds, 45)
        self.assertEqual(_health(_timing([1], finished_ago=-5)).age_seconds, 0)


class TestTickAgeText(unittest.TestCase):
    def test_seconds_under_a_minute_and_minutes_otherwise(self):
        self.assertEqual(tick_age_text(59), "59s")
        self.assertEqual(tick_age_text(60), "1m")
        self.assertEqual(tick_age_text(185), "3m")


class TestTickTimingRecorded(unittest.TestCase):
    def test_appends_and_sets_finished_at(self):
        prev = tick_timing_started(7, 100.0)
        t = tick_timing_recorded(prev, 7, 110.0, 2.0, 300)
        self.assertEqual((t.pid, t.finished_at, t.ticks), (7, 110.0, ((110.0, 2.0),)))

    def test_prunes_ticks_older_than_the_window(self):
        prev = TickTiming(7, 100.0, ((100.0, 1.0), (390.0, 1.0)))
        t = tick_timing_recorded(prev, 7, 450.0, 2.0, 300)
        self.assertEqual(t.ticks, ((390.0, 1.0), (450.0, 2.0)))

    def test_restarts_from_empty_when_the_pid_differs(self):
        prev = TickTiming(7, 100.0, ((100.0, 1.0),))
        t = tick_timing_recorded(prev, 8, 110.0, 2.0, 300)
        self.assertEqual(t.ticks, ((110.0, 2.0),))

    def test_starts_from_empty_without_a_previous(self):
        self.assertEqual(tick_timing_recorded(None, 7, 1.0, 2.0, 300).ticks, ((1.0, 2.0),))


class TestTickTimingFromState(unittest.TestCase):
    def test_round_trips_as_dict(self):
        t = TickTiming(7, 5.0, ((1.0, 2.0), (3.0, 4.0)))
        self.assertEqual(tick_timing_from_state(t.as_dict()), t)

    def test_rejects_malformed_shapes(self):
        good = {"pid": 1, "finished_at": 2.0, "ticks": [[1.0, 2.0]]}
        bad = [
            None, [], "x", {}, {**good, "pid": True}, {**good, "finished_at": "1"},
            {**good, "ticks": "x"}, {**good, "ticks": [[1.0]]}, {**good, "ticks": [[1.0, True]]},
            {**good, "ticks": [1.0]}, {"pid": 1, "finished_at": 2.0},
        ]
        for state in bad:
            self.assertIsNone(tick_timing_from_state(state), state)
        self.assertIsNotNone(tick_timing_from_state(good))
