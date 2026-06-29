import unittest

from the_grid.core.retro import derive_signals, gather_feedback
from the_grid.domain.task import Task


def tk(**kw):
    return Task(**kw)


def _hist(*statuses):
    """Build a bd-format history list (newest-first) from status names."""
    return [{"Issue": {"status": s}} for s in reversed(statuses)]


class TestDeriveSignals(unittest.TestCase):
    def test_review_rounds_counts_rejected_reviews(self):
        tasks = [
            tk(id="t1", step="review", outcome="rejected"),
            tk(id="t2", step="review", outcome="done"),
        ]
        sigs = derive_signals(tasks, {})
        self.assertEqual(sigs["review_rounds"], 1)

    def test_conflict_detected(self):
        tasks = [tk(id="t1", step="open-pr", outcome="conflict-rebase")]
        sigs = derive_signals(tasks, {})
        self.assertTrue(sigs["conflict"])

    def test_no_conflict_when_outcome_is_done(self):
        tasks = [tk(id="t1", step="open-pr", outcome="done")]
        sigs = derive_signals(tasks, {})
        self.assertFalse(sigs["conflict"])

    def test_blocks_counted_from_in_progress_to_open(self):
        tasks = [tk(id="t1", step="build", outcome=None)]
        sigs = derive_signals(tasks, {"t1": _hist("in_progress", "open")})
        self.assertEqual(sigs["blocks"], 1)

    def test_blocks_zero_when_no_regression(self):
        tasks = [tk(id="t1", step="build", outcome=None)]
        sigs = derive_signals(tasks, {"t1": _hist("open", "in_progress")})
        self.assertEqual(sigs["blocks"], 0)

    def test_blocks_counts_multiple_transitions(self):
        tasks = [tk(id="t1", step="build", outcome=None)]
        history = _hist("in_progress", "open", "in_progress", "open")
        sigs = derive_signals(tasks, {"t1": history})
        self.assertEqual(sigs["blocks"], 2)

    def test_non_build_tasks_ignored_for_blocks(self):
        tasks = [tk(id="t1", step="review", outcome=None)]
        sigs = derive_signals(tasks, {"t1": _hist("in_progress", "open")})
        self.assertEqual(sigs["blocks"], 0)

    def test_empty_tasks(self):
        sigs = derive_signals([], {})
        self.assertEqual(sigs, {"blocks": 0, "review_rounds": 0, "conflict": False})

    def test_missing_history_treated_as_empty(self):
        tasks = [tk(id="t1", step="build", outcome=None)]
        sigs = derive_signals(tasks, {})
        self.assertEqual(sigs["blocks"], 0)


class TestGatherFeedback(unittest.TestCase):
    def test_collects_feedback_with_task_ids(self):
        refs = [
            {"task": "t1", "feedback": "pytest not found"},
            {"task": "t2", "feedback": "spec was thin on error cases"},
        ]
        got = gather_feedback(refs)
        self.assertEqual(got, [
            {"task": "t1", "feedback": "pytest not found"},
            {"task": "t2", "feedback": "spec was thin on error cases"},
        ])

    def test_skips_empty_and_whitespace_feedback(self):
        refs = [
            {"task": "t1", "feedback": ""},
            {"task": "t2", "feedback": "   "},
            {"task": "t3", "feedback": "real feedback"},
        ]
        got = gather_feedback(refs)
        self.assertEqual([g["task"] for g in got], ["t3"])

    def test_missing_feedback_key_tolerated(self):
        self.assertEqual(gather_feedback([{"task": "t1"}]), [])

    def test_empty_reflections(self):
        self.assertEqual(gather_feedback([]), [])


if __name__ == "__main__":
    unittest.main()
