import unittest

from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.flow.simulate_plan import build_coverage_plan

CONTRACT_METAS = {
    "coder": {
        "step": "build",
        "accepts": {"spec": "required"},
        "produces": {"branch": "required"},
    },
    "reviewer": {
        "step": "review",
        "accepts": {"branch": "required"},
    },
}

_BRANCH_GRAPH = """
entry: build

edges:
  build   done      review
  review  done      merged
  review  rejected  build
"""


def _plan(text, metas=CONTRACT_METAS):
    graph = parse_graph(text)
    flow = Flow.from_graph(graph, metas)
    return build_coverage_plan(graph, flow), graph, flow


class TestBranchCoverage(unittest.TestCase):
    def test_both_outcomes_covered_across_walks(self):
        plan, _, _ = _plan(_BRANCH_GRAPH)
        covered = set()
        for walk in plan.walks:
            covered |= walk.covered()
        self.assertIn(("edge", "review", "done"), covered)
        self.assertIn(("edge", "review", "rejected"), covered)
        self.assertIn(("edge", "build", "done"), covered)


_CI_CAP_GRAPH = """
entry: build

edges:
  build      done         watch
  watch      done         review
  watch      ci-failed    build
  review     done         merged

hooks:
  ci_failed_cap    watch   ci-failed   2   review-ci
"""

_CI_CAP_METAS = {
    "coder": {"step": "build"},
    "watcher": {"step": "watch"},
    "reviewer": {"step": "review"},
    "ci-reviewer": {"step": "review-ci"},
}


class TestCiFailedCapCoverage(unittest.TestCase):
    def test_forced_repeat_walk_hits_the_cap_n_plus_one_times(self):
        plan, _, _ = _plan(_CI_CAP_GRAPH, _CI_CAP_METAS)
        repeat_walks = [
            w for w in plan.walks
            if any(s.repeat_total == 3 for s in w.steps)
        ]
        self.assertEqual(len(repeat_walks), 1)
        walk = repeat_walks[0]
        repeats = [s for s in walk.steps if s.stage == "watch" and s.outcome == "ci-failed"]
        self.assertEqual(len(repeats), 3)
        self.assertEqual([s.repeat_index for s in repeats], [1, 2, 3])
        self.assertTrue(repeats[-1].repeat_index == repeats[-1].repeat_total)


_PR_CONFLICT_GRAPH = """
entry: build

edges:
  build   done        open-pr
  open-pr done        await
  await   merged      cleanup
  await   conflicted  resolve
  resolve resolved    open-pr
  resolve escalate    gave-up

hooks:
  pr_conflict           await   conflicted
  pr_conflict_cap       await   2
  pr_conflict_escalate  await   gave-up
"""

_PR_CONFLICT_METAS = {
    "coder": {"step": "build"},
    "pr-watcher": {"step": "open-pr"},
    "merger": {"step": "await"},
    "resolver": {"step": "resolve"},
    "cleaner": {"step": "cleanup"},
}


class TestPrConflictCapCoverage(unittest.TestCase):
    def test_forced_repeat_walk_hits_the_conflict_cap_via_hooks(self):
        plan, _, _ = _plan(_PR_CONFLICT_GRAPH, _PR_CONFLICT_METAS)
        repeat_walks = [
            w for w in plan.walks
            if any(s.repeat_total == 3 and s.kind == "hook" for s in w.steps)
        ]
        self.assertEqual(len(repeat_walks), 1)
        walk = repeat_walks[0]
        repeats = [
            s for s in walk.steps
            if s.stage == "await" and s.kind == "hook" and s.hook == "pr_conflict"
        ]
        self.assertEqual(len(repeats), 3)
        self.assertEqual([s.repeat_index for s in repeats], [1, 2, 3])


_UNBOUNDED_LOOP_GRAPH = """
entry: build

edges:
  build   done      watch
  watch   ci-failed build
"""

_UNBOUNDED_LOOP_METAS = {
    "coder": {"step": "build"},
    "watcher": {"step": "watch"},
}


class TestUnboundedLoopIsBounded(unittest.TestCase):
    def test_planner_does_not_hang_and_returns_a_bounded_walk(self):
        plan, graph, flow = _plan(_UNBOUNDED_LOOP_GRAPH, _UNBOUNDED_LOOP_METAS)
        self.assertTrue(plan.walks)
        for walk in plan.walks:
            self.assertLess(len(walk.steps), 1000)


if __name__ == "__main__":
    unittest.main()
