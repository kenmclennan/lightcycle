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

hooks:
  pr_merge              ready-merge  merged
  pr_conflict           ready-merge  conflicted
  pr_conflict_cap       ready-merge  3
  pr_conflict_escalate  ready-merge  gave-up
  theme_close            audit
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
        self.assertEqual(self.flow.theme_close_steps(), [("audit", "auditor")])
        self.assertEqual(self.flow.retro_cadence_steps(), [("audit", "auditor")])

    def test_bare_terminal_has_no_owner_and_routes_to_human(self):
        self.assertIsNone(self.flow.owner_of("conflict-review"))
        self.assertEqual(self.flow.next("ready-merge", "gave-up").to_role, "human")
