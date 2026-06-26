import unittest

from the_grid.core.retro import aggregate_reflections, derive_signals


def _hist(*statuses):
    """Build a bd-format history list (newest-first) from status names."""
    return [{"Issue": {"status": s}} for s in reversed(statuses)]


class TestDeriveSignals(unittest.TestCase):
    def test_review_rounds_counts_rejected_reviews(self):
        tasks = [
            {"id": "t1", "step": "review", "outcome": "rejected"},
            {"id": "t2", "step": "review", "outcome": "done"},
        ]
        sigs = derive_signals(tasks, {})
        self.assertEqual(sigs["review_rounds"], 1)

    def test_conflict_detected(self):
        tasks = [{"id": "t1", "step": "open-pr", "outcome": "conflict-rebase"}]
        sigs = derive_signals(tasks, {})
        self.assertTrue(sigs["conflict"])

    def test_no_conflict_when_outcome_is_done(self):
        tasks = [{"id": "t1", "step": "open-pr", "outcome": "done"}]
        sigs = derive_signals(tasks, {})
        self.assertFalse(sigs["conflict"])

    def test_blocks_counted_from_in_progress_to_open(self):
        tasks = [{"id": "t1", "step": "build", "outcome": None}]
        sigs = derive_signals(tasks, {"t1": _hist("in_progress", "open")})
        self.assertEqual(sigs["blocks"], 1)

    def test_blocks_zero_when_no_regression(self):
        tasks = [{"id": "t1", "step": "build", "outcome": None}]
        sigs = derive_signals(tasks, {"t1": _hist("open", "in_progress")})
        self.assertEqual(sigs["blocks"], 0)

    def test_blocks_counts_multiple_transitions(self):
        tasks = [{"id": "t1", "step": "build", "outcome": None}]
        history = _hist("in_progress", "open", "in_progress", "open")
        sigs = derive_signals(tasks, {"t1": history})
        self.assertEqual(sigs["blocks"], 2)

    def test_non_build_tasks_ignored_for_blocks(self):
        tasks = [{"id": "t1", "step": "review", "outcome": None}]
        sigs = derive_signals(tasks, {"t1": _hist("in_progress", "open")})
        self.assertEqual(sigs["blocks"], 0)

    def test_empty_tasks(self):
        sigs = derive_signals([], {})
        self.assertEqual(sigs, {"blocks": 0, "review_rounds": 0, "conflict": False})

    def test_missing_history_treated_as_empty(self):
        tasks = [{"id": "t1", "step": "build", "outcome": None}]
        sigs = derive_signals(tasks, {})
        self.assertEqual(sigs["blocks"], 0)


class TestAggregateReflections(unittest.TestCase):
    def test_section_counts(self):
        refs = [
            {"sections": {"Summary": "used", "Risks": "skipped"}},
            {"sections": {"Summary": "used", "Risks": "guess"}},
        ]
        agg = aggregate_reflections(refs)
        sc = agg["section_counts"]
        self.assertEqual(sc["Summary"]["used"], 2)
        self.assertEqual(sc["Risks"]["skipped"], 1)
        self.assertEqual(sc["Risks"]["guess"], 1)

    def test_missing_counts(self):
        refs = [
            {"missing": ["acceptance criteria", "error cases"]},
            {"missing": ["acceptance criteria"]},
        ]
        agg = aggregate_reflections(refs)
        self.assertEqual(agg["missing_counts"]["acceptance criteria"], 2)
        self.assertEqual(agg["missing_counts"]["error cases"], 1)

    def test_noise_counts(self):
        refs = [{"noise": ["Out of scope"]}, {"noise": ["Out of scope"]}]
        agg = aggregate_reflections(refs)
        self.assertEqual(agg["noise_counts"]["Out of scope"], 2)

    def test_empty_reflections(self):
        agg = aggregate_reflections([])
        self.assertEqual(agg["section_counts"], {})
        self.assertEqual(len(agg["missing_counts"]), 0)
        self.assertEqual(len(agg["noise_counts"]), 0)

    def test_missing_and_noise_keys_absent_are_tolerated(self):
        refs = [{"sections": {"X": "used"}}]
        agg = aggregate_reflections(refs)
        self.assertEqual(len(agg["missing_counts"]), 0)
        self.assertEqual(len(agg["noise_counts"]), 0)

    def test_unknown_verdict_ignored(self):
        refs = [{"sections": {"X": "invalid"}}]
        agg = aggregate_reflections(refs)
        sc = agg["section_counts"]["X"]
        self.assertEqual(sc["used"] + sc["skipped"] + sc["guess"], 0)


if __name__ == "__main__":
    unittest.main()
