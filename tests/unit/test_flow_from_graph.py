import unittest

from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph

GRAPH_TEXT = """
entry: build

nodes:
  build   coder
  review  reviewer
  audit   auditor

edges:
  build        done      review
  review       done      open-pr
  review       rejected  build
  open-pr      done      watch-pr  primary
  watch-pr     done      ready-merge
  ready-merge  merged    cleanup
  ready-merge  gave-up   conflict-review
  audit        findings  review-findings
  audit        clean

hooks:
  pr_merge              ready-merge  merged
  pr_feedback           ready-merge  handle-feedback
  pr_conflict           ready-merge  conflicted
  pr_conflict_cap       ready-merge  3
  pr_conflict_escalate  ready-merge  gave-up
  ci_failed_cap         watch-pr     ci-failed  3  review-ci
  mention_token         ready-merge  @lc
  review_bot_allowlist  ready-merge  copilot-pull-request-reviewer[bot]  another-bot[bot]
"""

STEP_METAS = {
    "coder": {"model": "sonnet", "accepts": {"spec": "required"}, "produces": {"branch": "required"}},
    "reviewer": {"model": "sonnet"},
    "open-pr": {"model": "sonnet"},
    "watch-pr": {"model": "sonnet"},
    "ready-merge": {},
    "cleanup": {},
    "auditor": {"model": "sonnet"},
    "handle-feedback": {"model": "sonnet"},
    "review-findings": {},
    "review-ci": {},
}


class TestFlowFromGraph(unittest.TestCase):
    def setUp(self):
        self.graph = parse_graph(GRAPH_TEXT)
        self.flow = Flow.from_graph(self.graph, STEP_METAS)

    def test_a_stage_whose_step_file_declares_a_model_is_owned_by_the_agent_role(self):
        self.assertEqual(self.flow.step_def("build").owner, "agent")
        self.assertEqual(self.flow.step_def("review").owner, "agent")
        self.assertEqual(self.flow.step_def("audit").owner, "agent")

    def test_the_owner_never_carries_the_stage_or_its_step_file(self):
        for stage in ("build", "review", "audit"):
            self.assertNotIn(self.flow.step_def(stage).owner, (stage, self.graph.file_for(stage)))

    def test_stage_with_a_step_file_but_no_model_is_human(self):
        self.assertEqual(self.flow.step_def("ready-merge").owner, "human")

    def test_routing_carries_target_and_role(self):
        t = self.flow.next("build", "done")
        self.assertEqual(t.to_step, "review")
        self.assertEqual(t.to_role, "agent")
        self.assertEqual(self.flow.next("review", "rejected").to_step, "build")

    def test_terminal_and_conflict_outcomes(self):
        self.assertEqual(self.flow.step_def("ready-merge").pr_merge, "merged")
        self.assertEqual(self.flow.step_def("ready-merge").pr_conflict, "conflicted")
        self.assertEqual(self.flow.step_def("ready-merge").pr_conflict_cap, 3)
        self.assertEqual(self.flow.step_def("ready-merge").pr_conflict_escalate, "gave-up")

    def test_pr_feedback_step_registers_as_a_stage(self):
        self.assertEqual(self.flow.step_def("ready-merge").pr_feedback, "handle-feedback")
        self.assertEqual(self.flow.step_def("handle-feedback").owner, "agent")

    def test_pr_feedback_step_absent_by_default(self):
        self.assertIsNone(self.flow.step_def("build").pr_feedback)

    def test_mention_token_and_review_bot_allowlist(self):
        self.assertEqual(self.flow.step_def("ready-merge").mention_token, "@lc")
        self.assertEqual(
            self.flow.step_def("ready-merge").review_bot_allowlist,
            {"copilot-pull-request-reviewer[bot]", "another-bot[bot]"},
        )

    def test_mention_token_and_review_bot_allowlist_absent_by_default(self):
        self.assertIsNone(self.flow.step_def("build").mention_token)
        self.assertEqual(self.flow.step_def("build").review_bot_allowlist, frozenset())

    def test_bare_terminal_has_no_owner_and_routes_to_human(self):
        self.assertIsNone(self.flow.step_def("conflict-review").owner)
        self.assertEqual(self.flow.next("ready-merge", "gave-up").to_role, "human")

    def test_audit_findings_routes_to_review_findings(self):
        t = self.flow.next("audit", "findings")
        self.assertEqual(t.to_step, "review-findings")
        self.assertEqual(t.to_role, "human")

    def test_audit_clean_is_a_declared_terminal_outcome(self):
        self.assertIsNone(self.flow.next("audit", "clean"))
        self.assertIn("clean", self.flow.step_def("audit").routes.keys())

    def test_ci_failed_cap_and_target(self):
        cap = self.flow.step_def("watch-pr").ci_cap
        self.assertEqual(cap.outcome, "ci-failed")
        self.assertEqual(cap.n, 3)
        self.assertEqual(cap.target, "review-ci")

    def test_ci_failed_cap_absent_by_default(self):
        self.assertIsNone(self.flow.step_def("build").ci_cap)

    def test_ci_failed_cap_escalation_target_is_a_known_terminal_human_step(self):
        self.assertEqual(self.flow.step_def("review-ci").owner, "human")
        self.assertEqual(sorted(self.flow.step_def("review-ci").routes.keys()), [])

    def test_effective_transition_non_matching_outcome_is_never_redirected(self):
        raw = self.flow.next("watch-pr", "done")
        self.assertIs(self.flow.effective_transition(raw, "done", 100), raw)

    def test_effective_transition_no_cap_configured_is_a_no_op(self):
        raw = self.flow.next("build", "done")
        self.assertIs(self.flow.effective_transition(raw, "done", 100), raw)

    def test_effective_transition_none_transition_stays_none(self):
        self.assertIsNone(self.flow.effective_transition(None, "ci-failed", 5))

    def test_primary_outcome_returns_the_marked_outcome(self):
        self.assertEqual(self.flow.step_def("open-pr").primary, "done")

    def test_primary_outcome_absent_by_default(self):
        self.assertIsNone(self.flow.step_def("review").primary)

    def test_display_of_absent_by_default(self):
        self.assertIsNone(self.flow.step_def("build").display)


DISPLAY_GRAPH_TEXT = """
entry: build

nodes:
  build    coder
  review   reviewer
  cleanup  cleaner

edges:
  build   done  review

display:
  build   Coding
  review  Review the PR
"""


class TestFlowDisplayOf(unittest.TestCase):
    def setUp(self):
        self.flow = Flow.from_graph(parse_graph(DISPLAY_GRAPH_TEXT), STEP_METAS)

    def test_returns_the_declared_phrase(self):
        self.assertEqual(self.flow.step_def("build").display, "Coding")
        self.assertEqual(self.flow.step_def("review").display, "Review the PR")

    def test_returns_none_for_a_stage_with_no_declared_phrase(self):
        self.assertIsNone(self.flow.step_def("cleanup").display)

    def test_returns_none_for_an_undeclared_stage_named_audit(self):
        self.assertIsNone(self.flow.step_def("audit").display)


DISPOSITION_GRAPH_TEXT = """
entry: build

edges:
  build  done  review

disposition:
  merged     completed
  abandoned  aborted
"""


class TestFlowDispositionFor(unittest.TestCase):
    def test_threads_the_graphs_disposition_block_through(self):
        flow = Flow.from_graph(parse_graph(DISPOSITION_GRAPH_TEXT), STEP_METAS)
        self.assertEqual(flow.disposition_for("merged"), "completed")
        self.assertEqual(flow.disposition_for("abandoned"), "aborted")

    def test_returns_none_for_an_outcome_the_bundle_does_not_declare(self):
        flow = Flow.from_graph(parse_graph(DISPOSITION_GRAPH_TEXT), STEP_METAS)
        self.assertIsNone(flow.disposition_for("wontfix"))

    def test_a_workflow_with_no_disposition_block_still_parses(self):
        flow = Flow.from_graph(parse_graph("entry: build\n\nedges:\n  build  done  review\n"), STEP_METAS)
        self.assertIsNone(flow.disposition_for("done"))
