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
  open-pr      done      watch-pr
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
  retro_cadence         audit
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
        self.flow = Flow.from_graph(parse_graph(GRAPH_TEXT), STEP_METAS)

    def test_owner_from_stage_file_and_model(self):
        self.assertEqual(self.flow.owner_of("build"), "coder")
        self.assertEqual(self.flow.owner_of("review"), "reviewer")
        self.assertEqual(self.flow.owner_of("audit"), "auditor")

    def test_stage_with_a_step_file_but_no_model_is_human(self):
        self.assertEqual(self.flow.owner_of("ready-merge"), "human")

    def test_routing_carries_target_and_role(self):
        t = self.flow.next("build", "done")
        self.assertEqual(t.to_step, "review")
        self.assertEqual(t.to_role, "reviewer")
        self.assertEqual(self.flow.next("review", "rejected").to_step, "build")

    def test_terminal_and_conflict_outcomes(self):
        self.assertEqual(self.flow.terminal_merge_outcome(), "merged")
        self.assertEqual(self.flow.pr_conflict_outcome("ready-merge"), "conflicted")
        self.assertEqual(self.flow.pr_conflict_cap("ready-merge"), 3)
        self.assertEqual(self.flow.pr_conflict_escalate("ready-merge"), "gave-up")

    def test_lifecycle_hook_steps(self):
        self.assertEqual(self.flow.retro_cadence_steps(), [("audit", "auditor")])

    def test_pr_feedback_step_registers_as_a_stage(self):
        self.assertEqual(self.flow.pr_feedback_step("ready-merge"), "handle-feedback")
        self.assertEqual(self.flow.owner_of("handle-feedback"), "handle-feedback")

    def test_pr_feedback_step_absent_by_default(self):
        self.assertIsNone(self.flow.pr_feedback_step("build"))

    def test_mention_token_and_review_bot_allowlist(self):
        self.assertEqual(self.flow.mention_token("ready-merge"), "@lc")
        self.assertEqual(
            self.flow.review_bot_allowlist("ready-merge"),
            {"copilot-pull-request-reviewer[bot]", "another-bot[bot]"},
        )

    def test_mention_token_and_review_bot_allowlist_absent_by_default(self):
        self.assertIsNone(self.flow.mention_token("build"))
        self.assertEqual(self.flow.review_bot_allowlist("build"), set())

    def test_bare_terminal_has_no_owner_and_routes_to_human(self):
        self.assertIsNone(self.flow.owner_of("conflict-review"))
        self.assertEqual(self.flow.next("ready-merge", "gave-up").to_role, "human")

    def test_audit_findings_routes_to_review_findings(self):
        t = self.flow.next("audit", "findings")
        self.assertEqual(t.to_step, "review-findings")
        self.assertEqual(t.to_role, "human")

    def test_audit_clean_is_a_declared_terminal_outcome(self):
        self.assertIsNone(self.flow.next("audit", "clean"))
        self.assertIn("clean", self.flow.outcomes_for("audit"))

    def test_ci_failed_cap_and_target(self):
        self.assertEqual(self.flow.ci_failed_cap_outcome("watch-pr"), "ci-failed")
        self.assertEqual(self.flow.ci_failed_cap_n("watch-pr"), 3)
        self.assertEqual(self.flow.ci_failed_cap_target("watch-pr"), "review-ci")

    def test_ci_failed_cap_absent_by_default(self):
        self.assertIsNone(self.flow.ci_failed_cap_outcome("build"))
        self.assertIsNone(self.flow.ci_failed_cap_n("build"))
        self.assertIsNone(self.flow.ci_failed_cap_target("build"))

    def test_ci_failed_cap_escalation_target_is_a_known_terminal_human_step(self):
        self.assertEqual(self.flow.owner_of("review-ci"), "human")
        self.assertEqual(self.flow.outcomes_for("review-ci"), [])

    def test_effective_transition_non_matching_outcome_is_never_redirected(self):
        raw = self.flow.next("watch-pr", "done")
        self.assertIs(self.flow.effective_transition(raw, "done", 100), raw)

    def test_effective_transition_no_cap_configured_is_a_no_op(self):
        raw = self.flow.next("build", "done")
        self.assertIs(self.flow.effective_transition(raw, "done", 100), raw)

    def test_effective_transition_none_transition_stays_none(self):
        self.assertIsNone(self.flow.effective_transition(None, "ci-failed", 5))
