import unittest

from lightcycle.domain.flow.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.flow.step_def import CiCap, StepDef


class TestStepDef(unittest.TestCase):
    def test_defaults_are_empty(self):
        sd = StepDef()
        self.assertIsNone(sd.owner)
        self.assertEqual(sd.routes, {})
        self.assertIsNone(sd.ci_cap)
        self.assertEqual(sd.hooks, frozenset())
        self.assertIsNone(sd.primary)
        self.assertIsNone(sd.display)

    def test_ci_cap_holds_outcome_n_target(self):
        cap = CiCap("ci-failed", 3, "review-ci")
        self.assertEqual((cap.outcome, cap.n, cap.target), ("ci-failed", 3, "review-ci"))


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
        self.assertEqual(sd.review_bot_allowlist, frozenset({"bot-a", "bot-b"}))
        self.assertEqual(sd.ci_cap, CiCap("ci-failed", 3, "review-ci"))
        self.assertEqual(sd.workspace, "specs")
        self.assertEqual(sd.phase, "code")
        self.assertEqual(
            sd.hooks,
            frozenset({
                "on_pr_merge", "on_pr_close", "on_pr_feedback", "on_pr_conflict",
                "on_pr_conflict_cap", "on_pr_conflict_escalate", "on_mention_token",
                "on_review_bot_allowlist", "on_ci_failed_cap", "on_deploy_green",
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
        self.assertEqual(sd.review_bot_allowlist, frozenset())
        self.assertIsNone(sd.ci_cap)
        self.assertIsNone(sd.workspace)
        self.assertIsNone(sd.phase)
        self.assertEqual(sd.hooks, frozenset())
        self.assertIsNone(sd.display)


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
    def _flow(self):
        return Flow({
            "resolve": StepDef(
                pr_conflict="conflicted", pr_conflict_cap=2, pr_conflict_escalate="give-up"
            )
        })

    def test_below_cap_passes_the_conflict_outcome(self):
        self.assertEqual(self._flow().pr_conflict_transition("resolve", "conflicted", 0), "conflicted")
        self.assertEqual(self._flow().pr_conflict_transition("resolve", "conflicted", 1), "conflicted")

    def test_at_or_past_cap_escalates(self):
        self.assertEqual(self._flow().pr_conflict_transition("resolve", "conflicted", 2), "give-up")

    def test_no_cap_passes_through(self):
        flow = Flow({"resolve": StepDef()})
        self.assertEqual(flow.pr_conflict_transition("resolve", "conflicted", 9), "conflicted")


if __name__ == "__main__":
    unittest.main()
