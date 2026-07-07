import unittest

from lightcycle.domain.feedback import UNLABELED_MODEL, Reflection, Retro, SignalSpec
from lightcycle.domain.work import Node
from tests.support.fake_fs import signals_from_metas


def tk(**kw):
    kw.setdefault("id", "t")
    return Node(**kw)


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
        signals = signals_from_metas(self.METAS)
        steps = [
            tk(id="t1", step="review", outcome="rejected", model="sonnet"),
            tk(id="t2", step="review", outcome="done", model="sonnet"),
            tk(id="t3", step="open-pr", outcome="conflict-rebase", model="sonnet"),
        ]
        self.assertEqual(
            signals.tally(steps),
            {"review_rounds": {"sonnet": 1}, "conflicts": {"sonnet": 1}},
        )

    def test_tally_buckets_by_task_model(self):
        signals = signals_from_metas(self.METAS)
        steps = [
            tk(id="t1", step="review", outcome="rejected", model="opus"),
            tk(id="t2", step="review", outcome="rejected", model="sonnet"),
            tk(id="t3", step="review", outcome="rejected", model="sonnet"),
        ]
        self.assertEqual(
            signals.tally(steps), {"review_rounds": {"opus": 1, "sonnet": 2}, "conflicts": {}}
        )

    def test_tally_labels_missing_model_as_unlabeled(self):
        signals = signals_from_metas(self.METAS)
        steps = [tk(id="t1", step="review", outcome="rejected")]
        self.assertEqual(
            signals.tally(steps), {"review_rounds": {UNLABELED_MODEL: 1}, "conflicts": {}}
        )

    def test_tally_reports_empty_for_declared_but_unmatched(self):
        self.assertEqual(
            signals_from_metas(self.METAS).tally([]), {"review_rounds": {}, "conflicts": {}}
        )

    def test_no_declarations_gives_empty_tally(self):
        self.assertEqual(
            signals_from_metas({"coder": {"step": "build"}}).tally([tk(step="build")]), {}
        )

    def test_same_named_signal_across_steps_aggregates(self):
        metas = {
            "reviewer": {"step": "review", "signals": {"resets": "rejected"}},
            "watcher": {"step": "watch-pr", "signals": {"resets": "ci-failed"}},
            "merger": {"step": "ready-merge", "signals": {"resets": "changes"}},
        }
        steps = [
            tk(id="a", step="review", outcome="rejected", model="opus"),
            tk(id="b", step="watch-pr", outcome="ci-failed", model="sonnet"),
            tk(id="c", step="ready-merge", outcome="changes", model="sonnet"),
            tk(id="d", step="ready-merge", outcome="changes", model="sonnet"),
            tk(id="e", step="review", outcome="done", model="opus"),
        ]
        self.assertEqual(
            signals_from_metas(metas).tally(steps), {"resets": {"opus": 1, "sonnet": 3}}
        )


class TestRetro(unittest.TestCase):
    def test_collects_feedback_with_task_ids(self):
        refs = [
            Reflection(step="t1", feedback="pytest not found"),
            Reflection(step="t2", feedback="spec was thin on error cases"),
        ]
        self.assertEqual(
            Retro(refs).feedback(),
            [
                {"step": "t1", "feedback": "pytest not found"},
                {"step": "t2", "feedback": "spec was thin on error cases"},
            ],
        )

    def test_skips_empty_and_whitespace_feedback(self):
        refs = [
            Reflection(step="t1", feedback=""),
            Reflection(step="t2", feedback="   "),
            Reflection(step="t3", feedback="real feedback"),
        ]
        self.assertEqual([g["step"] for g in Retro(refs).feedback()], ["t3"])

    def test_empty_reflections(self):
        self.assertEqual(Retro([]).feedback(), [])


if __name__ == "__main__":
    unittest.main()
