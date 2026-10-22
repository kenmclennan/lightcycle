import unittest

from lightcycle.application.work import StepRunInput, StepRunUseCase
from tests.support.fake_store import FakeStore


class _PhaseFlow:
    def __init__(self, phase):
        self._phase = phase

    def phase_for(self, node):
        return self._phase


class TestStepRunUseCase(unittest.TestCase):
    def test_returns_branch_and_pr_from_the_steps_own_run(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step(stage="write-code", role="agent", item=item)
        pid = s.open_pass(item)
        s.set_step_pass(step, pid)
        rid = s.open_run(item, pid, "code")
        s.set_branch(rid, "feat/x")
        s.set_pr(rid, "https://gh/pr/1")

        result = StepRunUseCase(s, _PhaseFlow("code")).execute(StepRunInput(step=step))

        self.assertEqual(result.branch, "feat/x")
        self.assertEqual(result.pr, "https://gh/pr/1")

    def test_a_pass_holding_two_rounds_of_the_phase_resolves_to_the_newest(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step(stage="write-code", role="agent", item=item)
        pid = s.open_pass(item)
        s.set_step_pass(step, pid)
        first = s.open_run(item, pid, "amend")
        s.set_branch(first, "feat/x-amend")
        s.set_pr(first, "https://gh/pr/1")
        s.close_run(first, "merged")
        second = s.open_run(item, pid, "amend")
        s.set_branch(second, "feat/x-amend-r2")

        result = StepRunUseCase(s, _PhaseFlow("amend")).execute(StepRunInput(step=step))

        self.assertEqual(result.branch, "feat/x-amend-r2")
        self.assertIsNone(result.pr)

    def test_no_open_run_yields_no_branch_and_no_pr(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step(stage="write-code", role="agent", item=item)

        result = StepRunUseCase(s, _PhaseFlow("code")).execute(StepRunInput(step=step))

        self.assertIsNone(result.branch)
        self.assertIsNone(result.pr)


if __name__ == "__main__":
    unittest.main()
