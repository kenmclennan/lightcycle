import unittest
from pathlib import Path

from lightcycle.domain.flow.flow import Flow, pr_conflict_failures
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.flow.step_def import CiCap, ReviewRoundsCap, StepDef


class TestStepDef(unittest.TestCase):
    def test_defaults_are_empty(self):
        sd = StepDef()
        self.assertIsNone(sd.owner)
        self.assertEqual(sd.routes, {})
        self.assertIsNone(sd.ci_cap)
        self.assertIsNone(sd.review_rounds_cap)
        self.assertEqual(sd.hooks, frozenset())
        self.assertIsNone(sd.primary)
        self.assertIsNone(sd.display)

    def test_ci_cap_holds_outcome_n_target(self):
        cap = CiCap("ci-failed", 3, "review-ci")
        self.assertEqual((cap.outcome, cap.n, cap.target), ("ci-failed", 3, "review-ci"))

    def test_review_rounds_cap_holds_outcome_target(self):
        cap = ReviewRoundsCap("rejected", "review-rounds-exceeded")
        self.assertEqual((cap.outcome, cap.target), ("rejected", "review-rounds-exceeded"))


_EVERY_HOOK_TEXT = """
entry: build

edges:
  build   done     review           primary
  review  merged   cleanup
  review  changes  build

hooks:
  pr_merge              review  merged
  pr_close              review  abandoned
  pr_feedback           review  handle-feedback
  pr_conflict           review  conflicted
  pr_conflict_cap       review  3
  pr_conflict_escalate  review  gave-up
  mention_token         review  @lc
  review_bot_allowlist  review  bot-a  bot-b
  ci_failed_cap         review  ci-failed  3  review-ci
  review_rounds_cap     review  rejected  review-rounds-exceeded
  deploy_green          review  true

workspace:
  review  specs

phase:
  review  code

display:
  review  Review the PR
"""


class TestStepDefFromGraph(unittest.TestCase):
    def setUp(self):
        self.graph = parse_graph(_EVERY_HOOK_TEXT)

    def test_every_declared_hook_is_carried_onto_the_step_def(self):
        sd = StepDef.from_graph(self.graph, "review")
        self.assertEqual(sd.routes, {"merged": "cleanup", "changes": "build"})
        self.assertEqual(sd.pr_merge, "merged")
        self.assertEqual(sd.pr_close, "abandoned")
        self.assertEqual(sd.pr_feedback, "handle-feedback")
        self.assertEqual(sd.pr_conflict, "conflicted")
        self.assertEqual(sd.pr_conflict_cap, 3)
        self.assertEqual(sd.pr_conflict_escalate, "gave-up")
        self.assertEqual(sd.mention_token, "@lc")
        self.assertFalse(hasattr(sd, "review_bot_allowlist"))
        self.assertEqual(sd.ci_cap, CiCap("ci-failed", 3, "review-ci"))
        self.assertEqual(
            sd.review_rounds_cap, ReviewRoundsCap("rejected", "review-rounds-exceeded")
        )
        self.assertEqual(sd.workspace, "specs")
        self.assertEqual(sd.phase, "code")
        self.assertEqual(
            sd.hooks,
            frozenset({
                "on_pr_merge", "on_pr_close", "on_pr_feedback", "on_pr_conflict",
                "on_pr_conflict_cap", "on_pr_conflict_escalate", "on_mention_token",
                "on_review_bot_allowlist", "on_ci_failed_cap", "on_review_rounds_cap",
                "on_deploy_green",
            }),
        )
        self.assertEqual(sd.display, "Review the PR")

    def test_a_stage_with_no_declared_primary_edge_has_no_primary(self):
        self.assertIsNone(StepDef.from_graph(self.graph, "review").primary)

    def test_a_stage_marked_primary_carries_it(self):
        self.assertEqual(StepDef.from_graph(self.graph, "build").primary, "done")

    def test_a_stage_with_no_hooks_returns_the_field_defaults(self):
        sd = StepDef.from_graph(self.graph, "build")
        self.assertEqual(sd.routes, {"done": "review"})
        self.assertIsNone(sd.pr_merge)
        self.assertIsNone(sd.pr_close)
        self.assertIsNone(sd.pr_feedback)
        self.assertIsNone(sd.pr_conflict)
        self.assertIsNone(sd.pr_conflict_cap)
        self.assertIsNone(sd.pr_conflict_escalate)
        self.assertIsNone(sd.mention_token)
        self.assertIsNone(sd.ci_cap)
        self.assertIsNone(sd.review_rounds_cap)
        self.assertIsNone(sd.workspace)
        self.assertIsNone(sd.phase)
        self.assertEqual(sd.hooks, frozenset())
        self.assertIsNone(sd.display)


class TestMalformedCiFailedCap(unittest.TestCase):
    def test_below_minimum_occurrence_leaves_ci_cap_none(self):
        for occurrence in ("review", "review  ci-failed", "review  ci-failed  3"):
            with self.subTest(occurrence=occurrence):
                graph = parse_graph(
                    "entry: build\n\nhooks:\n  ci_failed_cap  %s\n" % occurrence
                )
                sd = StepDef.from_graph(graph, "review")
                self.assertIsNone(sd.ci_cap)


class TestFlowStepDef(unittest.TestCase):
    def test_returns_the_stored_step_def(self):
        sd = StepDef(phase="spec")
        flow = Flow({"s": sd})
        self.assertIs(flow.step_def("s"), sd)

    def test_returns_a_null_step_def_for_an_absent_stage(self):
        self.assertEqual(Flow({}).step_def("missing"), StepDef())
        self.assertEqual(Flow({"s": StepDef()}).step_def("other"), StepDef())


class TestPhase(unittest.TestCase):
    def test_flow_phase_of_returns_the_declared_phase(self):
        flow = Flow({"s": StepDef(phase="spec"), "c": StepDef(phase="code")})
        self.assertEqual(flow.step_def("s").phase, "spec")
        self.assertEqual(flow.step_def("c").phase, "code")

    def test_flow_phase_of_is_none_when_undeclared(self):
        self.assertIsNone(Flow({"s": StepDef()}).step_def("s").phase)
        self.assertIsNone(Flow({}).step_def("missing").phase)


class TestDisplay(unittest.TestCase):
    def test_flow_display_of_returns_the_declared_phrase(self):
        flow = Flow({"s": StepDef(display="Writing the spec"), "c": StepDef(display="Coding")})
        self.assertEqual(flow.step_def("s").display, "Writing the spec")
        self.assertEqual(flow.step_def("c").display, "Coding")

    def test_flow_display_of_is_none_when_undeclared(self):
        self.assertIsNone(Flow({"s": StepDef()}).step_def("s").display)
        self.assertIsNone(Flow({}).step_def("missing").display)


class TestConflictTransition(unittest.TestCase):
    def _flow(self, total=None):
        return Flow({
            "resolve": StepDef(
                pr_conflict="conflicted", pr_conflict_cap=2, pr_conflict_escalate="give-up",
                pr_conflict_total_cap=total,
            )
        })

    def _transition(self, flow, failures, prior):
        return flow.pr_conflict_transition("resolve", "conflicted", failures, prior)

    def test_below_cap_passes_the_conflict_outcome(self):
        self.assertEqual(self._transition(self._flow(), 0, 0), "conflicted")
        self.assertEqual(self._transition(self._flow(), 1, 1), "conflicted")

    def test_failures_at_or_past_cap_escalate(self):
        self.assertEqual(self._transition(self._flow(), 2, 0), "give-up")
        self.assertEqual(self._transition(self._flow(), 3, 0), "give-up")

    def test_prior_conflicts_alone_below_total_cap_do_not_escalate(self):
        self.assertEqual(self._transition(self._flow(), 0, 5), "conflicted")

    def test_prior_conflicts_at_derived_total_cap_escalate(self):
        self.assertEqual(self._transition(self._flow(), 0, 6), "give-up")

    def test_declared_total_cap_overrides_the_derived_one(self):
        flow = self._flow(total=4)
        self.assertEqual(self._transition(flow, 0, 3), "conflicted")
        self.assertEqual(self._transition(flow, 0, 4), "give-up")

    def test_no_cap_passes_through(self):
        flow = Flow({"resolve": StepDef()})
        self.assertEqual(flow.pr_conflict_transition("resolve", "conflicted", 9, 9), "conflicted")

    def test_no_escalate_outcome_never_escalates(self):
        flow = Flow({"resolve": StepDef(pr_conflict_cap=1)})
        self.assertEqual(flow.pr_conflict_transition("resolve", "conflicted", 9, 9), "conflicted")

    def test_failure_cap_is_named_when_both_trip(self):
        self.assertEqual(self._flow().pr_conflict_cap_fired("resolve", 2, 6), "pr_conflict_cap")
        self.assertEqual(
            self._flow().pr_conflict_cap_fired("resolve", 0, 6), "pr_conflict_total_cap")
        self.assertIsNone(self._flow().pr_conflict_cap_fired("resolve", 1, 1))

    def test_total_cap_is_three_times_the_failure_cap_unless_declared(self):
        self.assertEqual(self._flow().pr_conflict_total_cap("resolve"), 6)
        self.assertEqual(self._flow(total=5).pr_conflict_total_cap("resolve"), 5)
        self.assertIsNone(Flow({"resolve": StepDef()}).pr_conflict_total_cap("resolve"))


class TestCommittedBundleTotalCap(unittest.TestCase):
    def test_spec_driven_declares_no_total_cap_and_derives_nine(self):
        library = Path(__file__).resolve().parents[1] / "support" / "library"
        graph = parse_graph((library / "workflows" / "spec-driven.md").read_text())
        stage = "code-await-merge"
        flow = Flow({stage: StepDef.from_graph(graph, stage)})

        self.assertIsNone(flow.step_def(stage).pr_conflict_total_cap)
        self.assertEqual(flow.pr_conflict_total_cap(stage), 9)


class TestPrConflictFailures(unittest.TestCase):
    def test_empty_history_has_no_failures(self):
        self.assertEqual(pr_conflict_failures([], "A", 0), 0)

    def test_one_prior_step_on_the_same_tip_is_one_failure(self):
        self.assertEqual(pr_conflict_failures(["A"], "A", 0), 1)

    def test_one_prior_step_on_a_moved_tip_is_clean(self):
        self.assertEqual(pr_conflict_failures(["A"], "B", 0), 0)

    def test_unknown_entries_never_count(self):
        self.assertEqual(pr_conflict_failures(["A", "A", None], "A", 0), 1)
        self.assertEqual(pr_conflict_failures([None, None], None, 0), 0)

    def test_unknown_current_tip_is_clean(self):
        self.assertEqual(pr_conflict_failures(["A", "A"], None, 0), 1)

    def test_escalated_resolutions_add_to_the_count(self):
        self.assertEqual(pr_conflict_failures(["A"], "A", 2), 3)

    def test_unmoved_then_moved_then_unmoved_base(self):
        self.assertEqual(pr_conflict_failures(["A", "A", "B", "B"], "B", 0), 3)


if __name__ == "__main__":
    unittest.main()


class TestStaleBotAllowlistHook(unittest.TestCase):
    def test_a_declared_review_bot_allowlist_is_tolerated_and_unread(self):
        graph = parse_graph(_EVERY_HOOK_TEXT)
        sd = StepDef.from_graph(graph, "review")
        self.assertEqual(sd.mention_token, "@lc")
        self.assertEqual(sd.pr_merge, "merged")
        self.assertFalse(hasattr(sd, "review_bot_allowlist"))
