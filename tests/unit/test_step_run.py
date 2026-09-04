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
        step = s.create_step("s", step="write-code", role="agent", parent=item)
        pid = s.open_pass(item)
        s.set_step_pass(step, pid)
        rid = s.open_run(item, pid, "code")
        s.set_run_field(rid, branch="feat/x", pr="https://gh/pr/1")

        result = StepRunUseCase(s, _PhaseFlow("code")).execute(StepRunInput(step=step))

        self.assertEqual(result.branch, "feat/x")
        self.assertEqual(result.pr, "https://gh/pr/1")

    def test_no_open_run_yields_no_branch_and_no_pr(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step("s", step="write-code", role="agent", parent=item)

        result = StepRunUseCase(s, _PhaseFlow("code")).execute(StepRunInput(step=step))

        self.assertIsNone(result.branch)
        self.assertIsNone(result.pr)


if __name__ == "__main__":
    unittest.main()
