import unittest

from lightcycle.application.flow import ClaimInput, ClaimStepUseCase, CompleteInput, CompleteStepUseCase
from lightcycle.application.pool.release_interrupted_runs import ReleaseInterruptedRunsUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.close_item import (
    RELEASE_PENDING_LABEL, CloseItemInput, CloseItemUseCase,
)
from lightcycle.ports.git import GitReadError
from tests.support.fake_fs import FakeFs
from tests.support.fake_github_budget_status import FakeGithubBudgetStatus
from tests.support.fake_store import FakeStore
from tests.support.hold_notes import NoHoldNotes
from tests.unit.test_flow_usecases import FakeConfig as ClaimConfig
from tests.unit.test_flow_usecases import FakeWorkers as ClaimWorkers
from tests.unit.test_flow_usecases import FakeWorktrees as FakeClaimWorktrees
from tests.unit.test_github_budget import _budget

METAS = {"finaliser": {"model": "sonnet", "step": "finalise"}}


class _PassEndFlow(FlowService):
    def ends_pass(self, stage, outcome, name=None):
        return stage == "finalise" and outcome == "done"


class _FailingWorktrees:
    def __init__(self):
        self.failing = True

    def teardown_refusals(self, item, merged_prs=frozenset()):
        return []

    def pass_release_refusals(self, item, runs):
        return []

    def release_run(self, run, delete_remote=True):
        if self.failing:
            raise GitReadError("cut off")

    def remove(self, item):
        if self.failing:
            raise GitReadError("cut off")

    def path_for_run(self, run):
        return "/wt/%s" % run.id

    def release_interrupted(self, run):
        self.failing = False
        return True


def _claim(store, flow, role="agent"):
    uc = ClaimStepUseCase(
        store, flow, FakeClaimWorktrees(), ClaimWorkers(), ClaimConfig(),
        _budget(FakeGithubBudgetStatus(), flow))
    return uc.execute(ClaimInput(role=role))


class TestHoldAcrossAnInterruptedRelease(unittest.TestCase):
    def test_a_step_on_a_pass_end_with_a_cut_off_release_waits_for_the_gate(self):
        store = FakeStore()
        flow = _PassEndFlow(FakeFs(METAS), store)
        worktrees = _FailingWorktrees()
        item = store.create_item("story", "a description")
        pid = store.open_pass(item)
        rid = store.open_run(item, pid, "code")
        store.set_branch(rid, "feat/app-x")
        ender = store.create_step(stage="finalise", role="agent", item=item)
        store.assign(ender, "sp-1")
        store.update_state(ender, "running")

        CompleteStepUseCase(store, flow, worktrees).execute(
            CompleteInput(step=ender, outcome="done"))
        self.assertIn(RELEASE_PENDING_LABEL, store.labels_of(item))
        enrolled = store.create_step(stage="build", role="agent", item=item)

        self.assertIsNone(_claim(store, flow))
        ReleaseInterruptedRunsUseCase(store, worktrees, NoHoldNotes()).execute()

        self.assertNotIn(RELEASE_PENDING_LABEL, store.labels_of(item))
        self.assertEqual(_claim(store, flow).view.step.id, enrolled)

    def test_a_step_on_an_item_close_that_leaves_the_marker_waits_for_the_gate(self):
        store = FakeStore()
        flow = FlowService(FakeFs(METAS), store)
        worktrees = _FailingWorktrees()
        item = store.create_item("story", "a description")

        CloseItemUseCase(store, worktrees).execute(
            CloseItemInput(item=item, reason="done", disposition="completed"))
        self.assertIn(RELEASE_PENDING_LABEL, store.labels_of(item))
        late = store.create_step(stage="build", role="agent", item=item)

        self.assertIsNone(_claim(store, flow))
        ReleaseInterruptedRunsUseCase(store, worktrees, NoHoldNotes()).execute()

        self.assertEqual(_claim(store, flow).view.step.id, late)


if __name__ == "__main__":
    unittest.main()
