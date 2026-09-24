import unittest

from lightcycle.domain.work import SlowKind, State, Step, slow_steps


def _step(n, seconds, *, stage="review-code", turns=0, state=State.DONE, item="LC-1"):
    return Step(
        id="%s.%d" % (item, n), item=item, stage=stage, state=state,
        active_seconds=seconds, turn_count=turns,
    )


def _ladder(stage="review-code", count=20, turns=0, item="LC-1"):
    return [_step(n + 1, 60 * (n + 1), stage=stage, turns=turns, item=item) for n in range(count)]


class TestThreshold(unittest.TestCase):
    def test_flagged_at_exactly_twice_the_nearest_rank_p90(self):
        found = slow_steps(_ladder() + [_step(100, 2160)])

        self.assertEqual([s.step.id for s in found], ["LC-1.100"])
        self.assertEqual(found[0].threshold_seconds, 2160)
        self.assertEqual(found[0].baseline.p90_seconds, 1080)

    def test_one_second_below_the_threshold_is_not_flagged(self):
        self.assertEqual(slow_steps(_ladder() + [_step(100, 2159)]), [])

    def test_floor_governs_when_twice_p90_is_under_it(self):
        history = [_step(n + 1, 10 * (n + 1)) for n in range(20)]

        self.assertEqual([s.step.id for s in slow_steps(history + [_step(100, 600)])], ["LC-1.100"])
        self.assertEqual(slow_steps(history + [_step(100, 599)]), [])

    def test_stage_with_nineteen_other_steps_flags_nothing_at_any_duration(self):
        self.assertEqual(slow_steps(_ladder(count=19) + [_step(100, 10 ** 6)]), [])

    def test_stage_with_twenty_other_steps_is_measured(self):
        self.assertEqual(len(slow_steps(_ladder(count=20) + [_step(100, 10 ** 6)])), 1)

    def test_step_is_excluded_from_its_own_history(self):
        with_itself = _ladder() + [_step(100, 2160)]
        p90_including_itself = sorted(s.active_seconds for s in with_itself)[18]

        self.assertEqual(p90_including_itself, 1140)
        self.assertEqual(len(slow_steps(with_itself)), 1)

    def test_history_size_excludes_the_step_under_test(self):
        found = slow_steps(_ladder() + [_step(100, 2160)])

        self.assertEqual(found[0].baseline.history_size, 20)

    def test_duplicate_durations_do_not_shift_the_bound(self):
        history = [_step(n + 1, 100) for n in range(20)]

        self.assertEqual(len(slow_steps(history + [_step(100, 600)])), 1)
        self.assertEqual(slow_steps(history + [_step(100, 599)]), [])


class TestWhatCounts(unittest.TestCase):
    def test_stages_are_grouped_by_name_only(self):
        other_item = _step(100, 10 ** 6, item="LC-9")

        self.assertEqual(len(slow_steps(_ladder(item="LC-1") + [other_item])), 1)

    def test_a_stage_does_not_borrow_another_stages_history(self):
        found = slow_steps(_ladder(stage="write-code") + [_step(100, 10 ** 6, stage="review-code")])

        self.assertEqual(found, [])

    def test_null_stage_is_neither_candidate_nor_history(self):
        history = _ladder(count=19) + [_step(50, 5000, stage=None)]

        self.assertEqual(slow_steps(history + [_step(100, 10 ** 6)]), [])
        self.assertEqual(slow_steps([_step(101, 10 ** 6, stage=None)]), [])

    def test_null_and_zero_active_seconds_are_neither_candidate_nor_history(self):
        history = _ladder(count=19) + [_step(50, None), _step(51, 0), _step(52, -5)]

        self.assertEqual(slow_steps(history + [_step(100, 10 ** 6)]), [])

    def test_steps_that_are_not_done_are_not_history_or_candidates(self):
        history = _ladder(count=19) + [_step(50, 500, state=State.RUNNING)]

        self.assertEqual(slow_steps(history + [_step(100, 10 ** 6)]), [])
        self.assertEqual(slow_steps(_ladder() + [_step(100, 10 ** 6, state=State.RUNNING)]), [])

    def test_ordered_by_active_seconds_descending_then_node_id(self):
        extras = [
            _step(9, 9000, item="LC-2"), _step(100, 5000, item="LC-2"),
            _step(20, 5000, item="LC-2"), _step(3, 5000, item="LC-2"),
        ]

        history = [_step(n + 1, 10) for n in range(100)]

        found = slow_steps(history + extras)

        self.assertEqual([s.step.id for s in found], ["LC-2.9", "LC-2.3", "LC-2.20", "LC-2.100"])


class TestKind(unittest.TestCase):
    def _history_at_rate(self, turns_per_minute):
        return [
            _step(n + 1, 60 * (n + 1), turns=turns_per_minute * (n + 1))
            for n in range(20)
        ]

    def test_waiting_when_rate_is_at_exactly_half_the_median(self):
        found = slow_steps(self._history_at_rate(6) + [_step(100, 3000, turns=150)])

        self.assertEqual(found[0].kind, SlowKind.WAITING)
        self.assertEqual(found[0].baseline.median_turn_rate, 6)

    def test_working_when_rate_is_just_above_half_the_median(self):
        found = slow_steps(self._history_at_rate(6) + [_step(100, 3000, turns=151)])

        self.assertEqual(found[0].kind, SlowKind.WORKING)

    def test_the_real_record_reads_as_waiting_and_the_same_duration_with_more_turns_as_working(self):
        history = self._history_at_rate(7)

        waiting = slow_steps(history + [_step(100, 3167.5, turns=87)])
        working = slow_steps(history + [_step(100, 3167.5, turns=300)])

        self.assertEqual(waiting[0].kind, SlowKind.WAITING)
        self.assertEqual(working[0].kind, SlowKind.WORKING)

    def test_unknown_when_the_step_has_no_recorded_turns(self):
        found = slow_steps(self._history_at_rate(6) + [_step(100, 3000, turns=0)])

        self.assertEqual(found[0].kind, SlowKind.UNKNOWN)

    def test_unknown_when_no_other_step_at_the_stage_has_recorded_turns(self):
        found = slow_steps(_ladder(turns=0) + [_step(100, 3000, turns=50)])

        self.assertEqual(found[0].kind, SlowKind.UNKNOWN)
        self.assertIsNone(found[0].baseline.median_turn_rate)

    def test_the_step_under_test_does_not_contribute_to_its_own_median(self):
        found = slow_steps(_ladder(turns=0) + [_step(100, 3000, turns=1)])

        self.assertEqual(found[0].kind, SlowKind.UNKNOWN)
