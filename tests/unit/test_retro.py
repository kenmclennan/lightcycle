import unittest

from the_grid.domain.feedback import Reflection, Retro, SignalSpec, Signals
from the_grid.domain.work import Task


def tk(**kw):
    kw.setdefault("id", "t")
    return Task(**kw)


class TestSignalSpec(unittest.TestCase):
    def test_parse_exact(self):
        spec = SignalSpec.parse("review_rounds", "review", "rejected")
        self.assertEqual(
            (spec.name, spec.step, spec.outcome, spec.match),
            ("review_rounds", "review", "rejected", "exact"),
        )

    def test_parse_contains_via_tilde(self):
        spec = SignalSpec.parse("conflicts", "open-pr", "~conflict")
        self.assertEqual((spec.outcome, spec.match), ("conflict", "contains"))

    def test_matches_exact_outcome_and_step(self):
        spec = SignalSpec.parse("review_rounds", "review", "rejected")
        self.assertTrue(spec.matches(tk(step="review", outcome="rejected")))
        self.assertFalse(spec.matches(tk(step="review", outcome="done")))
        self.assertFalse(spec.matches(tk(step="build", outcome="rejected")))

    def test_matches_contains(self):
        spec = SignalSpec.parse("conflicts", "open-pr", "~conflict")
        self.assertTrue(spec.matches(tk(step="open-pr", outcome="conflict-rebase")))
        self.assertFalse(spec.matches(tk(step="open-pr", outcome="done")))


class TestSignals(unittest.TestCase):
    METAS = {
        "reviewer": {"step": "review", "signals": {"review_rounds": "rejected"}},
        "pr-watcher": {"step": "open-pr", "signals": {"conflicts": "~conflict"}},
        "coder": {"step": "build"},
        "driver": {"model": "opus"},
    }

    def test_from_metas_reads_declarations(self):
        signals = Signals.from_metas(self.METAS)
        tasks = [
            tk(id="t1", step="review", outcome="rejected"),
            tk(id="t2", step="review", outcome="done"),
            tk(id="t3", step="open-pr", outcome="conflict-rebase"),
        ]
        self.assertEqual(signals.tally(tasks), {"review_rounds": 1, "conflicts": 1})

    def test_tally_reports_zero_for_declared_but_unmatched(self):
        self.assertEqual(
            Signals.from_metas(self.METAS).tally([]), {"review_rounds": 0, "conflicts": 0}
        )

    def test_no_declarations_gives_empty_tally(self):
        self.assertEqual(
            Signals.from_metas({"coder": {"step": "build"}}).tally([tk(step="build")]), {}
        )

    def test_same_named_signal_across_steps_aggregates(self):
        metas = {
            "reviewer": {"step": "review", "signals": {"resets": "rejected"}},
            "watcher": {"step": "watch-pr", "signals": {"resets": "ci-failed"}},
            "merger": {"step": "ready-merge", "signals": {"resets": "changes"}},
        }
        tasks = [
            tk(id="a", step="review", outcome="rejected"),
            tk(id="b", step="watch-pr", outcome="ci-failed"),
            tk(id="c", step="ready-merge", outcome="changes"),
            tk(id="d", step="ready-merge", outcome="changes"),
            tk(id="e", step="review", outcome="done"),
        ]
        self.assertEqual(Signals.from_metas(metas).tally(tasks), {"resets": 4})


class TestRetro(unittest.TestCase):
    def test_collects_feedback_with_task_ids(self):
        refs = [
            Reflection(task="t1", feedback="pytest not found"),
            Reflection(task="t2", feedback="spec was thin on error cases"),
        ]
        self.assertEqual(
            Retro(refs).feedback(),
            [
                {"task": "t1", "feedback": "pytest not found"},
                {"task": "t2", "feedback": "spec was thin on error cases"},
            ],
        )

    def test_skips_empty_and_whitespace_feedback(self):
        refs = [
            Reflection(task="t1", feedback=""),
            Reflection(task="t2", feedback="   "),
            Reflection(task="t3", feedback="real feedback"),
        ]
        self.assertEqual([g["task"] for g in Retro(refs).feedback()], ["t3"])

    def test_empty_reflections(self):
        self.assertEqual(Retro([]).feedback(), [])


if __name__ == "__main__":
    unittest.main()
