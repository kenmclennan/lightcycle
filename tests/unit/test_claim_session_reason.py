import unittest

from lightcycle.application.flow import ClaimInput, ClaimStepUseCase
from lightcycle.application.work.stack_layers import StackLayers
from lightcycle.domain.pool.worker import Worker
from tests.support.fake_github import FakeGitHub
from tests.support.fake_github_budget import FakeGithubBudget
from tests.support.fake_store import FakeStore
from tests.unit.test_flow_usecases import FakeConfig, FakeWorkers, FakeWorktrees, flow_for
from tests.unit.test_step_model import METAS


class _FailingFreeze(FakeStore):
    def save_step_inputs(self, step, frozen_at, body):
        raise RuntimeError("freeze failed")


class TestClaimSessionReason(unittest.TestCase):
    def test_a_claim_that_raises_after_recording_its_log_marks_the_session_claim_failed(self):
        store = _FailingFreeze()
        item = store.create_item("t", "the brief", workflow="spec-driven", shortcode="APP")
        step = store.create_step(stage="build", role="agent", item=item)
        workers = FakeWorkers()
        workers.state = [Worker.from_state({"spawnid": "sp-1", "log": "/l/a.log", "role": "agent"})]
        use_case = ClaimStepUseCase(
            store, flow_for(METAS, store), FakeWorktrees(), workers, FakeConfig(spawn="sp-1"),
            FakeGithubBudget(), StackLayers(FakeGitHub()))

        with self.assertRaises(RuntimeError):
            use_case.execute(ClaimInput(role="agent"))

        sessions = store.step_sessions(step)
        self.assertEqual([(s.n, s.log_path) for s in sessions], [(1, "/l/a.log")])
        self.assertEqual(sessions[0].ended_reason, "claim-failed")
