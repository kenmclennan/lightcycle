import unittest
from types import SimpleNamespace

from lightcycle.application.workflows.simulate import (
    WorkflowSimulateUseCase, _pass_end_coverage_violations, _phase_mismatch,
)
from lightcycle.domain.flow.simulate_plan import CoveragePlan, PlannedStep, PlannedWalk
from tests.support.fake_store import FakeStore


class TestPhaseMismatch(unittest.TestCase):
    def test_matching_non_none_phases_produce_no_violation(self):
        self.assertEqual(
            _phase_mismatch(0, "pr_feedback", "gate", "target", "code", "code"), []
        )

    def test_differing_phases_produce_exactly_one_violation_naming_the_details(self):
        violations = _phase_mismatch(
            2, "pr_feedback", "spec-await-merge", "handle-feedback", "spec", "code"
        )
        self.assertEqual(len(violations), 1)
        msg = violations[0]
        self.assertIn("walk 2", msg)
        self.assertIn("pr_feedback", msg)
        self.assertIn("'spec-await-merge'", msg)
        self.assertIn("'handle-feedback'", msg)
        self.assertIn("'code'", msg)
        self.assertIn("'spec'", msg)

    def test_either_side_none_produces_no_violation(self):
        self.assertEqual(
            _phase_mismatch(0, "ci_failed_cap", "gate", "target", None, "code"), []
        )
        self.assertEqual(
            _phase_mismatch(0, "ci_failed_cap", "gate", "target", "code", None), []
        )
        self.assertEqual(
            _phase_mismatch(0, "ci_failed_cap", "gate", "target", None, None), []
        )


class _FakeGit:
    def __init__(self, torn_down_branches=()):
        self._torn_down_branches = tuple(torn_down_branches)

    def torn_down_branches(self):
        return self._torn_down_branches


def _use_case(store, git):
    return WorkflowSimulateUseCase(store, None, None, None, None, None, git)


class TestPassEndCoverageViolations(unittest.TestCase):
    def test_an_exercised_pass_end_produces_no_violation(self):
        graph = SimpleNamespace(pass_ends={("cleanup", "done")})
        plan = CoveragePlan((
            PlannedWalk((
                PlannedStep(stage="cleanup", kind="edge", outcome="done", crosses_pass_end=True),
            )),
        ))
        self.assertEqual(_pass_end_coverage_violations(graph, plan), [])

    def test_an_unexercised_pass_end_produces_exactly_one_violation_naming_it(self):
        graph = SimpleNamespace(pass_ends={("cleanup", "done")})
        plan = CoveragePlan((PlannedWalk(()),))
        violations = _pass_end_coverage_violations(graph, plan)
        self.assertEqual(len(violations), 1)
        self.assertIn("cleanup", violations[0])
        self.assertIn("done", violations[0])


class TestPassBoundaryViolations(unittest.TestCase):
    def test_a_pass_that_is_still_open_is_exactly_one_did_not_close_violation(self):
        store = FakeStore()
        item = store.create_item("t", "d")
        pid = store.open_pass(item)
        before_pass = store.get_pass(pid)

        violations = _use_case(store, _FakeGit())._pass_boundary_violations(0, item, before_pass)

        self.assertEqual(len(violations), 1)
        self.assertIn("did not close", violations[0])

    def test_closed_pass_with_torn_down_runs_and_a_new_pass_open_is_clean(self):
        store = FakeStore()
        item = store.create_item("t", "d")
        pid = store.open_pass(item)
        before_pass = store.get_pass(pid)
        rid = store.open_run(item, pid, "code")
        store.set_run_field(rid, branch="feat/x")
        store.close_run(rid)
        store.close_pass(pid)
        store.open_pass(item)

        violations = _use_case(store, _FakeGit(torn_down_branches=[("root", "feat/x")]))\
            ._pass_boundary_violations(0, item, before_pass)

        self.assertEqual(violations, [])

    def test_a_run_whose_branch_was_not_torn_down_is_named_in_one_violation(self):
        store = FakeStore()
        item = store.create_item("t", "d")
        pid = store.open_pass(item)
        before_pass = store.get_pass(pid)
        rid = store.open_run(item, pid, "code")
        store.set_run_field(rid, branch="feat/leaked")
        store.close_run(rid)
        store.close_pass(pid)
        store.open_pass(item)

        violations = _use_case(store, _FakeGit())._pass_boundary_violations(0, item, before_pass)

        self.assertEqual(len(violations), 1)
        self.assertIn(rid, violations[0])
        self.assertIn("feat/leaked", violations[0])

    def test_when_the_crossing_also_closed_the_item_no_new_pass_violation_fires(self):
        store = FakeStore()
        item = store.create_item("t", "d")
        pid = store.open_pass(item)
        before_pass = store.get_pass(pid)
        store.close_pass(pid)
        store.close(item, "done")

        violations = _use_case(store, _FakeGit())._pass_boundary_violations(0, item, before_pass)

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
