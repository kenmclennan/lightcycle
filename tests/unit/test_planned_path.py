import unittest

from lightcycle.domain.flow import Flow, planned_path
from lightcycle.domain.flow.graph import parse_graph

CHAIN_GRAPH_TEXT = """
entry: build

nodes:
  build   coder
  review  reviewer
  audit   auditor

edges:
  build   done  review
  review  done  audit
  audit   clean
"""

CHAIN_METAS = {
    "coder": {"model": "sonnet"},
    "reviewer": {"model": "sonnet"},
    "auditor": {"model": "sonnet"},
}

MERGE_GRAPH_TEXT = """
entry: build

nodes:
  build        coder
  await-merge  human
  cleanup      human
  fixup        coder

edges:
  build        done         await-merge
  await-merge  merged       cleanup
  await-merge  changes      fixup
  await-merge  conflicted   fixup
  await-merge  gave-up      cleanup
  fixup        done         await-merge

hooks:
  pr_merge               await-merge  merged
  pr_feedback            await-merge  fixup
  pr_conflict            await-merge  conflicted
  pr_conflict_cap        await-merge  3
  pr_conflict_escalate   await-merge  gave-up
"""

MERGE_METAS = {
    "coder": {"model": "sonnet"},
    "human": {},
}

CI_CAP_GRAPH_TEXT = """
entry: watch-ci

nodes:
  watch-ci     watcher
  ready-merge  human
  build        coder

edges:
  watch-ci     done       ready-merge
  watch-ci     ci-failed  build

hooks:
  ci_failed_cap  watch-ci  ci-failed  3  build
"""

CI_CAP_METAS = {
    "watcher": {"model": "sonnet"},
    "human": {},
    "coder": {"model": "sonnet"},
}

TERMINAL_GRAPH_TEXT = """
entry: review

nodes:
  review  reviewer

edges:
  review  done
"""

TERMINAL_METAS = {
    "reviewer": {"model": "sonnet"},
}

UNDETERMINABLE_GRAPH_TEXT = """
entry: build

nodes:
  build     coder
  open-pr   opener
  watch-ci  watcher

edges:
  build     done        open-pr
  open-pr   done        watch-ci
  open-pr   conflicted  build
"""

UNDETERMINABLE_METAS = {
    "coder": {"model": "sonnet"},
    "opener": {"model": "sonnet"},
    "watcher": {"model": "sonnet"},
}

PRIMARY_MARKED_GRAPH_TEXT = """
entry: build

nodes:
  build     coder
  open-pr   opener
  watch-ci  watcher

edges:
  build     done        open-pr
  open-pr   done        watch-ci  primary
  open-pr   conflicted  build
"""

PRIMARY_MARKED_METAS = {
    "coder": {"model": "sonnet"},
    "opener": {"model": "sonnet"},
    "watcher": {"model": "sonnet"},
}


class TestPlannedPathSingleOutcomeChain(unittest.TestCase):
    def test_returns_every_stage_up_to_the_terminal_edge_in_order(self):
        flow = Flow.from_graph(parse_graph(CHAIN_GRAPH_TEXT), CHAIN_METAS)
        self.assertEqual(
            planned_path(flow, "build"),
            [("review", "agent"), ("audit", "agent")],
        )


class TestPlannedPathMergeGatedBranch(unittest.TestCase):
    def test_follows_only_the_pr_merge_outcome(self):
        flow = Flow.from_graph(parse_graph(MERGE_GRAPH_TEXT), MERGE_METAS)
        self.assertEqual(planned_path(flow, "await-merge"), [("cleanup", "human")])


class TestPlannedPathCiFailedCapGatedBranch(unittest.TestCase):
    def test_follows_only_the_non_capped_outcome(self):
        flow = Flow.from_graph(parse_graph(CI_CAP_GRAPH_TEXT), CI_CAP_METAS)
        self.assertEqual(planned_path(flow, "watch-ci"), [("ready-merge", "human")])


class TestPlannedPathTerminalStep(unittest.TestCase):
    def test_returns_empty_list_from_a_terminal_outcome(self):
        flow = Flow.from_graph(parse_graph(TERMINAL_GRAPH_TEXT), TERMINAL_METAS)
        self.assertEqual(planned_path(flow, "review"), [])


class TestPlannedPathUndeterminableBranch(unittest.TestCase):
    def test_stops_at_the_undeterminable_branch_without_raising(self):
        flow = Flow.from_graph(parse_graph(UNDETERMINABLE_GRAPH_TEXT), UNDETERMINABLE_METAS)
        self.assertEqual(planned_path(flow, "build"), [("open-pr", "agent")])


class TestPlannedPathPrimaryMarkedBranch(unittest.TestCase):
    def test_follows_the_primary_marked_outcome_past_the_branch(self):
        flow = Flow.from_graph(parse_graph(PRIMARY_MARKED_GRAPH_TEXT), PRIMARY_MARKED_METAS)
        self.assertEqual(
            planned_path(flow, "build"),
            [("open-pr", "agent"), ("watch-ci", "agent")],
        )


if __name__ == "__main__":
    unittest.main()
