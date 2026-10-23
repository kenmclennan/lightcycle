import unittest
from types import SimpleNamespace

from lightcycle.application.workflows.simulate import _named_workspaces

from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.flow.simulate_plan import (
    build_coverage_plan, _walk_from_entry, _feedback_walk, _pass_boundary_walk,
    _edge_transitions, PlannedStep, PlannedWalk,
    _cap_occurrences, _forced_repeat_walk, _hook_transitions, _targetless_occurrences,
    _targetless_walk, _outgoing, _bfs_to_terminal, _pass_end_hook,
)

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


def _plan(text, metas=CONTRACT_METAS, review_rounds_cap_n=None):
    graph = parse_graph(text)
    flow = Flow.from_graph(graph, metas)
    return build_coverage_plan(graph, flow, review_rounds_cap_n), graph, flow


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


_RR_CAP_GRAPH = """
entry: build

edges:
  build      done      review
  review     done      merged
  review     rejected  build

hooks:
  review_rounds_cap    review   rejected   review-rounds-exceeded
"""

_RR_CAP_METAS = {
    "coder": {"step": "build"},
    "reviewer": {"step": "review"},
    "escalation-reviewer": {"step": "review-rounds-exceeded"},
}


class TestReviewRoundsCapCoverage(unittest.TestCase):
    def test_forced_repeat_walk_hits_the_cap_n_plus_one_times(self):
        plan, _, _ = _plan(_RR_CAP_GRAPH, _RR_CAP_METAS, review_rounds_cap_n=2)
        repeat_walks = [
            w for w in plan.walks
            if any(s.repeat_total == 3 for s in w.steps)
        ]
        self.assertEqual(len(repeat_walks), 1)
        walk = repeat_walks[0]
        repeats = [s for s in walk.steps if s.stage == "review" and s.outcome == "rejected"]
        self.assertEqual(len(repeats), 3)
        self.assertEqual([s.repeat_index for s in repeats], [1, 2, 3])
        self.assertTrue(repeats[-1].repeat_index == repeats[-1].repeat_total)

    def test_no_walk_generated_when_n_is_not_supplied(self):
        plan, _, _ = _plan(_RR_CAP_GRAPH, _RR_CAP_METAS)
        self.assertFalse(any(s.repeat_total for w in plan.walks for s in w.steps))

    def test_existing_ci_failed_cap_and_pr_conflict_cap_walks_are_unaffected(self):
        plan, _, _ = _plan(_CI_CAP_GRAPH, _CI_CAP_METAS, review_rounds_cap_n=2)
        repeat_walks = [
            w for w in plan.walks
            if any(s.repeat_total == 3 for s in w.steps)
        ]
        self.assertEqual(len(repeat_walks), 1)
        repeats = [s for s in repeat_walks[0].steps if s.stage == "watch" and s.outcome == "ci-failed"]
        self.assertEqual(len(repeats), 3)


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

        self.assertEqual(_named_workspaces(graph, "specs"), {"blueprints"})

    def test_the_item_repo_and_specs_need_no_seeding(self):
        graph = self._graph({"spec-writer": "specs", "build": "project"})

        self.assertEqual(_named_workspaces(graph, "specs"), set())

    def test_a_named_default_workspace_is_seeded_too(self):
        graph = self._graph({}, default="blueprints")

        self.assertEqual(_named_workspaces(graph, "specs"), {"blueprints"})

    def test_the_configured_context_project_needs_no_seeding(self):
        graph = self._graph({"a": "docs", "b": "specs"})

        self.assertEqual(_named_workspaces(graph, "docs"), {"specs"})

    def test_every_distinct_named_workspace_is_reported_once(self):
        graph = self._graph(
            {"a": "blueprints", "b": "blueprints", "c": "docs", "d": "specs"}
        )

        self.assertEqual(_named_workspaces(graph, "specs"), {"blueprints", "docs"})


_PASS_END_EDGE_GRAPH = """
entry: build

edges:
  build    done    review
  review   done    cleanup
  review   escape  finish
  cleanup  done    build

pass-end:
  cleanup  done
"""


class TestPassEndCoverageEdgeKind(unittest.TestCase):
    def test_a_declared_edge_kind_pass_end_gets_a_dedicated_crossing_walk(self):
        graph = parse_graph(_PASS_END_EDGE_GRAPH)
        plan = build_coverage_plan(graph, None)

        crossing = PlannedStep(
            stage="cleanup", kind="edge", outcome="done", crosses_pass_end=True
        )
        matching = [w for w in plan.walks if crossing in w.steps]
        self.assertEqual(len(matching), 1)
        self.assertFalse(matching[0].incomplete)


_PASS_END_HOOK_GRAPH = """
entry: build

edges:
  build    done    review
  review   done    cleanup
  review   escape  finish
  cleanup  done    build

hooks:
  pr_merge  cleanup  done

pass-end:
  cleanup  done
"""


class TestPassEndCoverageHookKind(unittest.TestCase):
    def test_a_declared_hook_kind_pass_end_is_driven_via_the_hook_not_an_edge(self):
        graph = parse_graph(_PASS_END_HOOK_GRAPH)
        plan = build_coverage_plan(graph, None)

        crossing = [
            s for w in plan.walks for s in w.steps
            if s.stage == "cleanup" and s.outcome == "done" and s.crosses_pass_end
        ]
        self.assertEqual(len(crossing), 1)
        self.assertEqual(crossing[0].kind, "hook")
        self.assertEqual(crossing[0].hook, "pr_merge")


_MIXED_PASS_END_GRAPH = """
entry: build

edges:
  build        done       review
  build        merge-out  await-merge
  review       done       cleanup
  review       escape     finish
  cleanup      done       build
  await-merge  merged     build

hooks:
  pr_merge  await-merge  merged

pass-end:
  cleanup      done
  await-merge  merged
"""


class TestMixedPassEndCoverage(unittest.TestCase):
    def test_both_an_edge_kind_and_a_hook_kind_pass_end_get_their_own_walk(self):
        graph = parse_graph(_MIXED_PASS_END_GRAPH)
        plan = build_coverage_plan(graph, None)

        edge_crossing = [
            s for w in plan.walks for s in w.steps
            if s.stage == "cleanup" and s.outcome == "done" and s.crosses_pass_end
        ]
        hook_crossing = [
            s for w in plan.walks for s in w.steps
            if s.stage == "await-merge" and s.outcome == "merged" and s.crosses_pass_end
        ]
        self.assertEqual(len(edge_crossing), 1)
        self.assertEqual(edge_crossing[0].kind, "edge")
        self.assertEqual(len(hook_crossing), 1)
        self.assertEqual(hook_crossing[0].kind, "hook")
        self.assertEqual(hook_crossing[0].hook, "pr_merge")


class TestNoPassEndLeavesCoveragePlanUnchanged(unittest.TestCase):
    def test_a_graph_with_no_declared_pass_end_produces_the_same_walks_as_before(self):
        graph = parse_graph(_CI_CAP_GRAPH)
        plan = build_coverage_plan(graph, None)

        self.assertEqual(len(plan.walks), 3)
        for step in (s for w in plan.walks for s in w.steps):
            self.assertFalse(step.crosses_pass_end)
        covered = set()
        for walk in plan.walks:
            covered |= walk.covered()
        self.assertEqual(
            covered,
            {
                ("edge", "build", "done"),
                ("edge", "watch", "done"),
                ("edge", "watch", "ci-failed"),
                ("edge", "review", "done"),
            },
        )


_PASS_END_UNREACHABLE_GRAPH = """
entry: build

edges:
  build  done  finish

pass-end:
  isolated  done
"""


class TestUnreachablePassEndGateReturnsEmptyWalk(unittest.TestCase):
    def test_pass_boundary_walk_returns_an_empty_walk_when_the_gate_is_unreachable(self):
        graph = parse_graph(_PASS_END_UNREACHABLE_GRAPH)

        walk = _pass_boundary_walk(graph, graph.entry, "isolated", "done", bound=8)

        self.assertEqual(walk, PlannedWalk(()))


_MIXED_TERMINAL_GRAPH = """
entry: build

edges:
  build   done    review
  build   clean
  review  done    merged
"""

_MIXED_TERMINAL_METAS = {
    "coder": {"step": "build"},
    "reviewer": {"step": "review"},
}

_TARGETLESS_TERMINAL_GRAPH = """
entry: build

edges:
  build      done  review-ci
  review-ci  reviewed
"""


class TestMixedStageTargetlessCoverage(unittest.TestCase):
    def test_the_targetless_outcome_of_a_mixed_stage_is_covered_by_some_walk(self):
        plan, _, _ = _plan(_MIXED_TERMINAL_GRAPH, _MIXED_TERMINAL_METAS)

        covered = set()
        for walk in plan.walks:
            covered |= walk.covered()

        self.assertIn(("edge", "build", "clean"), covered)

    def test_edge_transitions_includes_a_mixed_stages_targetless_outcome(self):
        graph = parse_graph(_MIXED_TERMINAL_GRAPH)

        self.assertIn(("edge", "build", "clean"), _edge_transitions(graph))

    def test_edge_transitions_excludes_a_pure_terminal_stages_targetless_outcome(self):
        graph = parse_graph(_TARGETLESS_TERMINAL_GRAPH)

        self.assertNotIn(("edge", "review-ci", "reviewed"), _edge_transitions(graph))


_ONLY_EXIT_IS_TARGETLESS_GRAPH = """
entry: build

edges:
  build   done    audit
  audit   remedial-filed  build
  audit   clean
"""

_ONLY_EXIT_IS_TARGETLESS_METAS = {
    "coder": {"step": "build"},
    "auditor": {"step": "audit"},
}


class TestTargetlessExitOnMixedStage(unittest.TestCase):
    def test_a_graph_whose_only_exit_is_a_mixed_stages_targetless_outcome_plans_no_incomplete_walk(self):
        plan, _, _ = _plan(_ONLY_EXIT_IS_TARGETLESS_GRAPH, _ONLY_EXIT_IS_TARGETLESS_METAS)

        self.assertFalse([w for w in plan.walks if w.incomplete])

    def test_every_walk_in_such_a_graph_ends_on_the_targetless_outcome(self):
        plan, _, _ = _plan(_ONLY_EXIT_IS_TARGETLESS_GRAPH, _ONLY_EXIT_IS_TARGETLESS_METAS)

        self.assertTrue(plan.walks)
        for walk in plan.walks:
            self.assertEqual(walk.steps[-1].key(), ("edge", "audit", "clean"))


_CI_CAP_OWNED_EDGE_GRAPH = """
entry: build

edges:
  build      done         watch
  watch      done         review
  watch      ci-failed    build
  review     done         merged
  review-ci  reviewed     merged

hooks:
  ci_failed_cap    watch   ci-failed   2   review-ci
"""

_CI_CAP_OWNED_EDGE_METAS = dict(_CI_CAP_METAS)


class TestCiFailedCapOwnedEdgeBearingTargetCoverage(unittest.TestCase):
    def test_walk_continues_past_the_escalation_target_to_a_real_terminal(self):
        plan, _, _ = _plan(_CI_CAP_OWNED_EDGE_GRAPH, _CI_CAP_OWNED_EDGE_METAS)
        repeat_walks = [w for w in plan.walks if any(s.repeat_total == 3 for s in w.steps)]
        self.assertEqual(len(repeat_walks), 1)
        walk = repeat_walks[0]
        self.assertFalse(walk.incomplete, walk.stuck_at)
        self.assertIn(("edge", "review-ci", "reviewed"), walk.covered())


_RR_CAP_OWNED_EDGE_GRAPH = """
entry: build

edges:
  build                    done      review
  review                   done      merged
  review                   rejected  build
  review-rounds-exceeded   reviewed  merged

hooks:
  review_rounds_cap    review   rejected   review-rounds-exceeded
"""

_RR_CAP_OWNED_EDGE_METAS = dict(_RR_CAP_METAS)


class TestReviewRoundsCapOwnedEdgeBearingTargetCoverage(unittest.TestCase):
    def test_walk_continues_past_the_escalation_target_to_a_real_terminal(self):
        plan, _, _ = _plan(_RR_CAP_OWNED_EDGE_GRAPH, _RR_CAP_OWNED_EDGE_METAS, review_rounds_cap_n=2)
        repeat_walks = [w for w in plan.walks if any(s.repeat_total == 3 for s in w.steps)]
        self.assertEqual(len(repeat_walks), 1)
        walk = repeat_walks[0]
        self.assertFalse(walk.incomplete, walk.stuck_at)
        self.assertIn(("edge", "review-rounds-exceeded", "reviewed"), walk.covered())


_PR_CONFLICT_OWNED_EDGE_GRAPH = """
entry: build

edges:
  build             done        open-pr
  open-pr           done        await
  await             merged      cleanup
  await             conflicted  resolve
  await             gave-up     review-conflict
  resolve           resolved    open-pr
  resolve           escalate    review-conflict
  review-conflict   resolved    open-pr

hooks:
  pr_conflict           await   conflicted
  pr_conflict_cap       await   2
  pr_conflict_escalate  await   gave-up
"""

_PR_CONFLICT_OWNED_EDGE_METAS = dict(_PR_CONFLICT_METAS)
_PR_CONFLICT_OWNED_EDGE_METAS["reviewer"] = {"step": "review-conflict"}


class TestPrConflictCapOwnedEdgeBearingTargetCoverage(unittest.TestCase):
    def test_walk_continues_past_the_escalation_target_to_a_real_terminal(self):
        plan, _, _ = _plan(_PR_CONFLICT_OWNED_EDGE_GRAPH, _PR_CONFLICT_OWNED_EDGE_METAS)
        repeat_walks = [
            w for w in plan.walks
            if any(s.repeat_total == 3 and s.kind == "hook" for s in w.steps)
        ]
        self.assertEqual(len(repeat_walks), 1)
        walk = repeat_walks[0]
        self.assertFalse(walk.incomplete, walk.stuck_at)
        self.assertIn(("edge", "review-conflict", "resolved"), walk.covered())


_CI_CAP_TARGETLESS_OUTCOME_GRAPH = """
entry: build

edges:
  build      done         watch
  watch      done         review
  review     done         merged
  review-ci  reviewed     merged

hooks:
  ci_failed_cap    watch   ci-failed   2   review-ci
"""

_CI_CAP_TARGETLESS_OUTCOME_METAS = dict(_CI_CAP_METAS)


class TestCiFailedCapTargetlessOutcomeDoesNotEscalate(unittest.TestCase):
    def test_no_escalation_tail_when_the_loop_back_outcome_has_no_edge_target(self):
        plan, _, _ = _plan(_CI_CAP_TARGETLESS_OUTCOME_GRAPH, _CI_CAP_TARGETLESS_OUTCOME_METAS)
        repeat_walks = [w for w in plan.walks if any(s.repeat_total == 3 for s in w.steps)]
        self.assertEqual(len(repeat_walks), 1)
        walk = repeat_walks[0]
        repeats = [s for s in walk.steps if s.stage == "watch" and s.outcome == "ci-failed"]
        self.assertEqual(len(repeats), 1)
        self.assertEqual(repeats[0].repeat_index, 1)
        self.assertEqual(repeats[0].repeat_total, 3)
        self.assertNotIn(("edge", "review-ci", "reviewed"), walk.covered())


_PR_CONFLICT_NO_BACK_PATH_GRAPH = """
entry: build

edges:
  build             done        open-pr
  open-pr           done        await
  await             merged      cleanup
  await             conflicted  resolve
  await             gave-up     review-conflict
  review-conflict   resolved    open-pr

hooks:
  pr_conflict           await   conflicted
  pr_conflict_cap       await   2
  pr_conflict_escalate  await   gave-up
"""

_PR_CONFLICT_NO_BACK_PATH_METAS = dict(_PR_CONFLICT_OWNED_EDGE_METAS)


class TestPrConflictCapEarlyBreakDoesNotEscalate(unittest.TestCase):
    def test_no_escalation_tail_when_the_repeats_cannot_reach_the_cap(self):
        plan, _, _ = _plan(_PR_CONFLICT_NO_BACK_PATH_GRAPH, _PR_CONFLICT_NO_BACK_PATH_METAS)
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
        self.assertEqual(len(repeats), 1)
        self.assertEqual(repeats[0].repeat_index, 1)
        self.assertEqual(repeats[0].repeat_total, 3)
        self.assertNotIn(("edge", "review-conflict", "resolved"), walk.covered())


def _e(stage, outcome, **kw):
    return PlannedStep(stage=stage, kind="edge", outcome=outcome, **kw)


def _h(stage, hook, outcome, **kw):
    return PlannedStep(stage=stage, kind="hook", hook=hook, outcome=outcome, **kw)


def _walks(plan):
    return [(w.steps, w.incomplete, w.stuck_at) for w in plan.walks]


class TestPlannedStepKey(unittest.TestCase):
    def test_an_edge_key_omits_the_hook_and_a_hook_key_carries_it(self):
        self.assertEqual(_e("s", "o").key(), ("edge", "s", "o"))
        self.assertEqual(_h("s", "pr_merge", "o").key(), ("hook", "pr_merge", "s", "o"))


class TestExactPlans(unittest.TestCase):
    def test_phase_graph_plan(self):
        plan, _, _ = _plan(_PHASE_GRAPH, _PHASE_GRAPH_METAS)
        self.assertEqual(_walks(plan), [
            ((_e("build", "done"), _e("watch", "done"), _e("await-merge", "merged")), False, None),
            ((_e("build", "done"), _e("watch", "ci-failed"), _e("build", "done"),
              _e("watch", "done"), _h("await-merge", "pr_merge", "merged")), False, None),
            ((_e("build", "done"),
              _e("watch", "ci-failed", repeat_index=1, repeat_total=3),
              _e("build", "done"),
              _e("watch", "ci-failed", repeat_index=2, repeat_total=3),
              _e("build", "done"),
              _e("watch", "ci-failed", repeat_index=3, repeat_total=3, expected_phase="code")),
             False, None),
            ((_e("build", "done"), _e("watch", "done"),
              _h("await-merge", "pr_feedback", "handle-feedback", expected_phase="code"),
              _e("await-merge", "merged")), False, None),
        ])

    def test_pr_conflict_plan(self):
        plan, _, _ = _plan(_PR_CONFLICT_GRAPH, _PR_CONFLICT_METAS)
        self.assertEqual(_walks(plan), [
            ((_e("build", "done"), _e("open-pr", "done"), _e("await", "conflicted"),
              _e("resolve", "escalate")), False, None),
            ((_e("build", "done"), _e("open-pr", "done"), _e("await", "merged")), False, None),
            ((_e("build", "done"), _e("open-pr", "done"), _h("await", "pr_conflict", "conflicted"),
              _e("resolve", "resolved"), _e("open-pr", "done"), _e("await", "merged")), False, None),
            ((_e("build", "done"), _e("open-pr", "done"),
              _h("await", "pr_conflict", "conflicted", repeat_index=1, repeat_total=3),
              _e("resolve", "resolved"), _e("open-pr", "done"),
              _h("await", "pr_conflict", "conflicted", repeat_index=2, repeat_total=3),
              _e("resolve", "resolved"), _e("open-pr", "done"),
              _h("await", "pr_conflict", "conflicted", repeat_index=3, repeat_total=3)),
             False, None),
        ])

    def test_review_rounds_cap_plan(self):
        plan, _, _ = _plan(_RR_CAP_GRAPH, _RR_CAP_METAS, review_rounds_cap_n=2)
        self.assertEqual(_walks(plan), [
            ((_e("build", "done"), _e("review", "done")), False, None),
            ((_e("build", "done"), _e("review", "rejected"), _e("build", "done"),
              _e("review", "done")), False, None),
            ((_e("build", "done"),
              _e("review", "rejected", repeat_index=1, repeat_total=3),
              _e("build", "done"),
              _e("review", "rejected", repeat_index=2, repeat_total=3),
              _e("build", "done"),
              _e("review", "rejected", repeat_index=3, repeat_total=3, expected_phase=None)),
             False, None),
        ])

    def test_mixed_pass_end_plan(self):
        plan = build_coverage_plan(parse_graph(_MIXED_PASS_END_GRAPH), None)
        tail = (_e("build", "done"), _e("review", "escape"))
        self.assertEqual(_walks(plan), [
            ((_e("build", "done"), _e("review", "done"), _e("cleanup", "done"),
              _e("build", "merge-out"), _e("await-merge", "merged")) + tail, False, None),
            ((_e("build", "done"), _e("review", "done"), _e("cleanup", "done"),
              _e("build", "merge-out"), _h("await-merge", "pr_merge", "merged")) + tail,
             False, None),
            ((_e("build", "merge-out"),
              _h("await-merge", "pr_merge", "merged", crosses_pass_end=True),
              _e("build", "done"), _e("review", "done"), _e("cleanup", "done"),
              _e("build", "merge-out"), _e("await-merge", "merged")) + tail, False, None),
            ((_e("build", "done"), _e("review", "done"), _e("cleanup", "done", crosses_pass_end=True),
              _e("build", "done"), _e("review", "done"), _e("cleanup", "done"),
              _e("build", "merge-out"), _e("await-merge", "merged")) + tail, False, None),
        ])

    def test_mixed_terminal_plan_ends_with_the_targetless_walk(self):
        plan, _, _ = _plan(_MIXED_TERMINAL_GRAPH, _MIXED_TERMINAL_METAS)
        self.assertEqual(_walks(plan), [
            ((_e("build", "done"), _e("review", "done")), False, None),
            ((_e("build", "done"), _e("review", "done")), False, None),
            ((_e("build", "clean"),), False, None),
        ])


_CAP_INTO_DEAD_END_GRAPH = """
entry: build

edges:
  build   done       watch
  watch   done       review
  watch   ci-failed  build
  review  done       merged
  esc     loop       esc

hooks:
  ci_failed_cap  watch  ci-failed  2  esc
"""


class TestEscalationThatCannotReachATerminal(unittest.TestCase):
    def test_the_cap_walk_is_incomplete_and_names_the_escalation_stage(self):
        graph = parse_graph(_CAP_INTO_DEAD_END_GRAPH)
        walk = _forced_repeat_walk(graph, "build", "watch", "ci-failed", 3, "edge", escalate_target="esc")
        self.assertTrue(walk.incomplete)
        self.assertEqual(walk.stuck_at, "esc")
        self.assertEqual(len(walk.steps), 6)

    def test_an_unreachable_stage_gives_an_empty_cap_walk(self):
        graph = parse_graph(_CAP_INTO_DEAD_END_GRAPH)
        self.assertEqual(_forced_repeat_walk(graph, "build", "esc", "loop", 3, "edge"), PlannedWalk(()))


class TestHelpersDirectly(unittest.TestCase):
    def test_hook_transitions_lists_pr_merge_and_pr_conflict_occurrences_only(self):
        self.assertEqual(
            _hook_transitions(parse_graph(_PHASE_GRAPH)),
            {("hook", "pr_merge", "await-merge", "merged")},
        )
        self.assertEqual(
            _hook_transitions(parse_graph(_PR_CONFLICT_GRAPH)),
            {("hook", "pr_conflict", "await", "conflicted")},
        )

    def test_targetless_occurrences_skips_pure_terminal_stages_and_keeps_scanning(self):
        graph = parse_graph("entry: build\n\nedges:\n  aa     x\n  bb     clean\n  bb     done  build\n  build  done  aa\n")
        self.assertEqual(_targetless_occurrences(graph), [("bb", "clean")])

    def test_cap_occurrences_omits_a_review_rounds_cap_with_no_supplied_limit(self):
        graph = parse_graph(
            "entry: build\n\nedges:\n  build   done      watch\n  watch   done      review\n"
            "  watch   ci-failed build\n  review  done      merged\n  review  rejected  build\n\n"
            "hooks:\n  review_rounds_cap  review  rejected  esc\n  ci_failed_cap  watch  ci-failed  2  esc2\n")
        self.assertEqual(_cap_occurrences(graph, None), [("edge", None, "watch", "ci-failed", 2, "esc2")])

    def test_targetless_and_unreachable_walks(self):
        graph = parse_graph(_CAP_INTO_DEAD_END_GRAPH)
        self.assertEqual(_targetless_walk(graph, "build", "esc", "loop"), PlannedWalk(()))
        self.assertEqual(
            _targetless_walk(graph, "build", "watch", "ci-failed"),
            PlannedWalk((_e("build", "done"), _e("watch", "ci-failed"))),
        )

    def test_feedback_walk_to_an_unreachable_stage_is_empty(self):
        graph = parse_graph(_CAP_INTO_DEAD_END_GRAPH)
        self.assertEqual(_feedback_walk(graph, "build", "esc", "x", bound=8), PlannedWalk(()))

    def test_pass_boundary_walk_through_a_targetless_outcome_is_empty(self):
        graph = parse_graph(_MIXED_TERMINAL_GRAPH)
        self.assertEqual(_pass_boundary_walk(graph, "build", "build", "clean", bound=8), PlannedWalk(()))

    def test_pass_boundary_walk_propagates_an_incomplete_resume(self):
        graph = parse_graph(_UNBOUNDED_LOOP_GRAPH)
        walk = _pass_boundary_walk(graph, "build", "watch", "ci-failed", bound=4)
        self.assertTrue(walk.incomplete)
        self.assertEqual(walk.stuck_at, "build")
        self.assertEqual(walk.steps[0], _e("build", "done"))
        self.assertEqual(walk.steps[1], _e("watch", "ci-failed", crosses_pass_end=True))

    def test_feedback_walk_carries_the_feedback_step_and_the_gates_phase(self):
        graph = parse_graph(_PHASE_GRAPH)
        walk = _feedback_walk(graph, "build", "await-merge", "handle-feedback", bound=8)
        self.assertEqual(
            walk.steps[:3],
            (_e("build", "done"), _e("watch", "done"),
             _h("await-merge", "pr_feedback", "handle-feedback", expected_phase="code")),
        )


class TestBoundSizing(unittest.TestCase):
    def test_a_single_transition_loop_is_cut_at_four_steps(self):
        graph = parse_graph("entry: a\n\nedges:\n  a  loop  a\n")
        walk = build_coverage_plan(graph, None).walks[0]
        self.assertEqual(len(walk.steps), 4)
        self.assertTrue(walk.incomplete)
        self.assertEqual(walk.stuck_at, "a")

    def test_a_two_transition_loop_is_cut_at_eight_steps(self):
        plan, _, _ = _plan(_UNBOUNDED_LOOP_GRAPH, _UNBOUNDED_LOOP_METAS)
        stuck = [w for w in plan.walks if w.incomplete][0]
        self.assertEqual(len(stuck.steps), 8)


_OTHER_STAGE_HOOK_GRAPH = """
entry: a

edges:
  a  merged  b
  b  merged  c

hooks:
  pr_merge  b  merged
"""


class TestHooksOfOtherStagesAreNotOptions(unittest.TestCase):
    def test_outgoing_offers_only_the_stages_own_hook_occurrences(self):
        graph = parse_graph(_OTHER_STAGE_HOOK_GRAPH)
        self.assertEqual(_outgoing(graph, "a"), [_e("a", "merged")])
        self.assertEqual(_outgoing(graph, "b"), [_e("b", "merged"), _h("b", "pr_merge", "merged")])

    def test_pass_end_hook_ignores_a_hook_on_another_stage_with_the_same_outcome(self):
        graph = parse_graph(_OTHER_STAGE_HOOK_GRAPH)
        self.assertIsNone(_pass_end_hook(graph, "a", "merged"))
        self.assertEqual(_pass_end_hook(graph, "b", "merged"), "pr_merge")


class TestBfsToTerminalFromAStageWithAnExit(unittest.TestCase):
    def test_a_start_stage_with_a_targetless_outcome_exits_immediately(self):
        graph = parse_graph(_MIXED_TERMINAL_GRAPH)
        self.assertEqual(_bfs_to_terminal(graph, "build"), [_e("build", "clean")])
        self.assertEqual(_bfs_to_terminal(graph, "review"), [_e("review", "done")])


_HOOK_ORDER_GRAPH = """
entry: s

edges:
  s  aa  x
  s  bb  y
  s  zz  z

hooks:
  pr_merge     s  zz
  pr_conflict  s  bb
"""


class TestHookOptionsTieBreakByOutcome(unittest.TestCase):
    def test_equally_ranked_hook_options_are_taken_in_outcome_order(self):
        plan = build_coverage_plan(parse_graph(_HOOK_ORDER_GRAPH), None)
        self.assertEqual(
            [w.steps for w in plan.walks],
            [
                (_e("s", "aa"),),
                (_e("s", "bb"),),
                (_e("s", "zz"),),
                (_h("s", "pr_conflict", "bb"),),
                (_h("s", "pr_merge", "zz"),),
            ],
        )
