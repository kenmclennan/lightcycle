import unittest
from types import SimpleNamespace

from lightcycle.application.workflows.simulate import _named_workspaces

from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.flow.simulate_plan import build_coverage_plan, _walk_from_entry, _feedback_walk

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

    def test_a_walk_with_no_reachable_terminal_is_reported_incomplete(self):
        plan, graph, flow = _plan(_UNBOUNDED_LOOP_GRAPH, _UNBOUNDED_LOOP_METAS)
        stuck_walks = [w for w in plan.walks if w.incomplete]
        self.assertEqual(len(stuck_walks), 1)
        walk = stuck_walks[0]
        self.assertEqual(walk.stuck_at, "build")


_TIE_BREAK_GRAPH = """
entry: start

edges:
  start   done       decide
  decide  zzz-alt    term-a
  decide  aaa-first  term-b
"""

_TIE_BREAK_PRIMARY_GRAPH = """
entry: start

edges:
  start   done       decide
  decide  zzz-alt    term-a   primary
  decide  aaa-first  term-b
"""

_TIE_BREAK_METAS = {
    "coder": {"step": "start"},
    "decider": {"step": "decide"},
}


class TestPrimaryEdgeTieBreak(unittest.TestCase):
    def test_with_no_primary_marker_the_alphabetically_first_outcome_wins_the_tie(self):
        plan, _, _ = _plan(_TIE_BREAK_GRAPH, _TIE_BREAK_METAS)
        first_walk = plan.walks[0]
        decide_step = [s for s in first_walk.steps if s.stage == "decide"][0]
        self.assertEqual(decide_step.outcome, "aaa-first")

    def test_a_primary_marked_outcome_wins_the_tie_regardless_of_its_name(self):
        plan, _, _ = _plan(_TIE_BREAK_PRIMARY_GRAPH, _TIE_BREAK_METAS)
        first_walk = plan.walks[0]
        decide_step = [s for s in first_walk.steps if s.stage == "decide"][0]
        self.assertEqual(decide_step.outcome, "zzz-alt")


_LONG_DETOUR_GRAPH = """
entry: a

edges:
  a   done   b
  b   done   c
  c   done   d
  d   done   e
"""


class TestTruncatedWalkCompletesToTheNearestTerminal(unittest.TestCase):
    def test_a_walk_that_hits_a_small_bound_still_reaches_the_terminal(self):
        graph = parse_graph(_LONG_DETOUR_GRAPH)
        walk = _walk_from_entry(graph, "a", set(), bound=2)
        self.assertFalse(walk.incomplete)
        self.assertIsNone(walk.stuck_at)
        self.assertEqual(walk.steps[-1].stage, "d")
        self.assertEqual(walk.steps[-1].outcome, "done")


_TWO_STEP_GRAPH = """
entry: a

edges:
  a  done  b
  b  done  c
"""


class TestBoundHitExactlyOnArrivalAtARealTerminalIsComplete(unittest.TestCase):
    def test_a_walk_that_reaches_a_real_terminal_exactly_at_the_bound_is_not_incomplete(self):
        graph = parse_graph(_TWO_STEP_GRAPH)
        walk = _walk_from_entry(graph, "a", set(), bound=2)
        self.assertFalse(walk.incomplete)
        self.assertIsNone(walk.stuck_at)
        self.assertEqual(walk.steps[-1].stage, "b")
        self.assertEqual(walk.steps[-1].outcome, "done")


_FEEDBACK_STUCK_GRAPH = """
entry: build

edges:
  build   done   review
  review  loop   build

hooks:
  pr_feedback   build   review
"""


class TestFeedbackWalkPropagatesIncomplete(unittest.TestCase):
    def test_a_feedback_walk_whose_resume_segment_cannot_reach_a_terminal_is_incomplete(self):
        graph = parse_graph(_FEEDBACK_STUCK_GRAPH)
        walk = _feedback_walk(graph, "build", "build", "review", bound=8)
        self.assertTrue(walk.incomplete)
        self.assertIsNotNone(walk.stuck_at)


class TestExistingBundlesRemainComplete(unittest.TestCase):
    def test_branch_ci_cap_and_pr_conflict_fixtures_produce_no_incomplete_walks(self):
        for text, metas in (
            (_BRANCH_GRAPH, CONTRACT_METAS),
            (_CI_CAP_GRAPH, _CI_CAP_METAS),
            (_PR_CONFLICT_GRAPH, _PR_CONFLICT_METAS),
        ):
            plan, _, _ = _plan(text, metas)
            for walk in plan.walks:
                self.assertFalse(walk.incomplete)


if __name__ == "__main__":
    unittest.main()


_PHASE_GRAPH = """
entry: build

phase:
  build            code
  watch            code
  await-merge      code
  handle-feedback  code
  review-ci        code

edges:
  build        done         watch
  watch        done         await-merge
  watch        ci-failed    build
  await-merge  merged       cleanup

hooks:
  pr_merge       await-merge  merged
  pr_feedback    await-merge  handle-feedback
  ci_failed_cap  watch        ci-failed   2  review-ci
"""

_NO_PHASE_GRAPH = _PHASE_GRAPH.replace(
    "phase:\n"
    "  build            code\n"
    "  watch            code\n"
    "  await-merge      code\n"
    "  handle-feedback  code\n"
    "  review-ci        code\n"
    "\n",
    "",
)

_PHASE_GRAPH_METAS = {
    "coder": {"step": "build"},
    "watcher": {"step": "watch"},
    "merger": {"step": "await-merge"},
    "feedback-handler": {"step": "handle-feedback"},
    "ci-reviewer": {"step": "review-ci"},
}


class TestExpectedPhaseOnFeedbackStep(unittest.TestCase):
    def test_pr_feedback_step_expects_the_gates_own_phase(self):
        plan, graph, _ = _plan(_PHASE_GRAPH, _PHASE_GRAPH_METAS)
        feedback_steps = [
            s for w in plan.walks for s in w.steps
            if s.kind == "hook" and s.hook == "pr_feedback"
        ]
        self.assertEqual(len(feedback_steps), 1)
        self.assertEqual(feedback_steps[0].expected_phase, graph.phase_for("await-merge"))
        self.assertEqual(feedback_steps[0].expected_phase, "code")


class TestExpectedPhaseIsNoneForOrdinaryAndAdvancingHookSteps(unittest.TestCase):
    def test_ordinary_edges_and_advancing_hook_steps_never_get_an_expected_phase(self):
        plan, _, _ = _plan(_PHASE_GRAPH, _PHASE_GRAPH_METAS)
        for walk in plan.walks:
            for step in walk.steps:
                is_ordinary_edge = step.kind == "edge" and step.repeat_total is None
                is_advancing_hook = step.kind == "hook" and step.hook == "pr_merge"
                if is_ordinary_edge or is_advancing_hook:
                    self.assertIsNone(step.expected_phase)


class TestExpectedPhaseOnlyOnFinalCiFailedCapRepeat(unittest.TestCase):
    def test_only_the_final_repeat_of_a_ci_failed_cap_walk_gets_an_expected_phase(self):
        plan, graph, _ = _plan(_PHASE_GRAPH, _PHASE_GRAPH_METAS)
        repeat_walks = [
            w for w in plan.walks
            if any(s.repeat_total == 3 for s in w.steps)
        ]
        self.assertEqual(len(repeat_walks), 1)
        repeats = [
            s for s in repeat_walks[0].steps
            if s.stage == "watch" and s.outcome == "ci-failed"
        ]
        self.assertEqual(len(repeats), 3)
        for r in repeats[:-1]:
            self.assertIsNone(r.expected_phase)
        self.assertEqual(repeats[-1].expected_phase, graph.phase_for("watch"))
        self.assertEqual(repeats[-1].expected_phase, "code")


_MIXED_CAP_GRAPH = """
entry: build

phase:
  build      code
  watch      code
  open-pr    code
  await      code
  resolve    code
  review-ci  code

edges:
  build    done        watch
  watch    done        open-pr
  watch    ci-failed   build
  open-pr  done        await
  await    merged      cleanup
  await    conflicted  resolve
  resolve  resolved    open-pr
  resolve  escalate    gave-up

hooks:
  ci_failed_cap    watch   ci-failed   2   review-ci
  pr_conflict      await   conflicted
  pr_conflict_cap  await   2
"""

_MIXED_CAP_METAS = {
    "coder": {"step": "build"},
    "watcher": {"step": "watch"},
    "pr-watcher": {"step": "open-pr"},
    "merger": {"step": "await"},
    "resolver": {"step": "resolve"},
    "ci-reviewer": {"step": "review-ci"},
}


class TestExpectedPhaseDistinguishesCiFailedCapFromPrConflictCap(unittest.TestCase):
    def test_only_the_ci_failed_cap_walks_final_repeat_gets_an_expected_phase(self):
        plan, graph, _ = _plan(_MIXED_CAP_GRAPH, _MIXED_CAP_METAS)

        ci_repeat_walks = [
            w for w in plan.walks
            if any(s.repeat_total == 3 and s.kind == "edge" for s in w.steps)
        ]
        self.assertEqual(len(ci_repeat_walks), 1)
        ci_repeats = [
            s for s in ci_repeat_walks[0].steps
            if s.stage == "watch" and s.outcome == "ci-failed"
        ]
        self.assertEqual(len(ci_repeats), 3)
        self.assertIsNone(ci_repeats[0].expected_phase)
        self.assertIsNone(ci_repeats[1].expected_phase)
        self.assertEqual(ci_repeats[2].expected_phase, graph.phase_for("watch"))

        conflict_repeat_walks = [
            w for w in plan.walks
            if any(s.repeat_total == 3 and s.kind == "hook" for s in w.steps)
        ]
        self.assertEqual(len(conflict_repeat_walks), 1)
        conflict_repeats = [
            s for s in conflict_repeat_walks[0].steps
            if s.stage == "await" and s.kind == "hook" and s.hook == "pr_conflict"
        ]
        self.assertEqual(len(conflict_repeats), 3)
        for r in conflict_repeats:
            self.assertIsNone(r.expected_phase)


class TestExpectedPhaseIsNoneWithoutAPhaseBlock(unittest.TestCase):
    def test_no_phase_block_means_no_expected_phase_anywhere(self):
        plan, _, _ = _plan(_NO_PHASE_GRAPH, _PHASE_GRAPH_METAS)
        for walk in plan.walks:
            for step in walk.steps:
                self.assertIsNone(step.expected_phase)


class TestNamedWorkspaceSeeding(unittest.TestCase):
    def _graph(self, workspaces, default="project"):
        return SimpleNamespace(workspaces=workspaces, workspace=default)

    def test_a_named_workspace_is_reported_for_seeding(self):
        graph = self._graph({"audit-design": "blueprints"})

        self.assertEqual(_named_workspaces(graph), {"blueprints"})

    def test_the_item_repo_and_specs_need_no_seeding(self):
        graph = self._graph({"spec-writer": "specs", "build": "project"})

        self.assertEqual(_named_workspaces(graph), set())

    def test_a_named_default_workspace_is_seeded_too(self):
        graph = self._graph({}, default="blueprints")

        self.assertEqual(_named_workspaces(graph), {"blueprints"})

    def test_every_distinct_named_workspace_is_reported_once(self):
        graph = self._graph(
            {"a": "blueprints", "b": "blueprints", "c": "docs", "d": "specs"}
        )

        self.assertEqual(_named_workspaces(graph), {"blueprints", "docs"})
