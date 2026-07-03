import os
import unittest

from the_grid.application.errors import UseCaseError
from the_grid.application.flow import (
    AdvanceInput,
    AdvanceTaskUseCase,
    BlockInput,
    BlockTaskUseCase,
    ClaimInput,
    ClaimTaskUseCase,
    CompleteInput,
    CompleteTaskUseCase,
    FlowCheckInput,
    FlowCheckUseCase,
    UnblockInput,
    UnblockTaskUseCase,
)
from the_grid.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

METAS = {
    "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
    "reviewer": {
        "model": "opus",
        "step": "review",
        "produces": {"pr": "required"},
        "routes": {"done": "open-pr", "rejected": "build"},
    },
}
SPEC_METAS = {
    "coder": {
        "model": "sonnet",
        "step": "build",
        "accepts": {"spec": "required"},
        "routes": {"done": "review"},
    },
}


def flow_for(metas, store):
    return FlowService(FakeFs(metas), store)


class FakeWorktrees:
    def ensure(self, story):
        return None

    def story_branch(self, story):
        return None


class FakeWorkers:
    def __init__(self):
        self.stamped = []

    def set_task(self, spawnid, task):
        self.stamped.append((spawnid, task))


class FakeConfig:
    def __init__(self, spawn=None):
        self._spawn = spawn

    def spawn_id(self):
        return self._spawn

    def specs_root(self):
        return "/specs"


class TestAdvanceTask(unittest.TestCase):
    def test_creates_next_task(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        resp = AdvanceTaskUseCase(s, flow_for(METAS, s)).execute(
            AdvanceInput(task=bid, outcome="done")
        )
        nt = s.get_task(resp.next_task)
        self.assertEqual(nt.step, "review")
        self.assertEqual(nt.role, "reviewer")

    def test_unknown_outcome_returns_none(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        resp = AdvanceTaskUseCase(s, flow_for(METAS, s)).execute(
            AdvanceInput(task=bid, outcome="nope")
        )
        self.assertIsNone(resp.next_task)


class TestCompleteTask(unittest.TestCase):
    def test_closes_and_advances(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        resp = CompleteTaskUseCase(s, flow_for(METAS, s)).execute(
            CompleteInput(task=bid, outcome="done")
        )
        self.assertEqual(s.get_task(bid).status, "done")
        self.assertEqual(s.get_task(resp.next_task).step, "review")

    def test_invalid_outcome_raises(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        with self.assertRaises(UseCaseError):
            CompleteTaskUseCase(s, flow_for(METAS, s)).execute(
                CompleteInput(task=bid, outcome="banana")
            )

    def test_missing_required_output_raises(self):
        s = FakeStore()
        story = s.create_story("st")
        rid = s.create_task("review: x", step="review", role="reviewer", parent=story)
        with self.assertRaises(UseCaseError):
            CompleteTaskUseCase(s, flow_for(METAS, s)).execute(
                CompleteInput(task=rid, outcome="done")
            )

    def test_terminal_step_closes_without_routing(self):
        terminal_metas = {"finaliser": {"model": "sonnet", "step": "finalise"}}
        s = FakeStore()
        tid = s.create_task("finalise: x", step="finalise", role="finaliser")
        resp = CompleteTaskUseCase(s, flow_for(terminal_metas, s)).execute(
            CompleteInput(task=tid, outcome="done")
        )
        self.assertEqual(s.get_task(tid).status, "done")
        self.assertIsNone(resp.next_task)

    def test_step_with_routes_unknown_outcome_still_errors(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        with self.assertRaises(UseCaseError):
            CompleteTaskUseCase(s, flow_for(METAS, s)).execute(
                CompleteInput(task=bid, outcome="typo")
            )


class TestClaimTask(unittest.TestCase):
    def _uc(self, store, config=None):
        return ClaimTaskUseCase(
            store, flow_for(METAS, store), FakeWorktrees(), FakeWorkers(), config or FakeConfig()
        )

    def test_claims_ready_task(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertEqual(resp.view.task.id, bid)

    def test_nothing_ready_returns_none(self):
        self.assertIsNone(self._uc(FakeStore()).execute(ClaimInput(role="coder")))

    def test_stamps_spawn_id_when_present(self):
        s = FakeStore()
        s.create_task("build: x", step="build", role="coder")
        workers = FakeWorkers()
        ClaimTaskUseCase(
            s, flow_for(METAS, s), FakeWorktrees(), workers, FakeConfig(spawn="sp1")
        ).execute(ClaimInput(role="coder"))
        self.assertEqual(len(workers.stamped), 1)

    def test_missing_required_input_routes_to_human(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        resp = ClaimTaskUseCase(
            s, flow_for(SPEC_METAS, s), FakeWorktrees(), FakeWorkers(), FakeConfig()
        ).execute(ClaimInput(role="coder"))
        self.assertIsNone(resp)
        self.assertEqual(s.get_task(bid).role, "human")

    def test_resolves_spec_path_against_specs_root(self):
        s = FakeStore()
        story = s.create_story("st")
        s.add_artifact(story, "spec", "specs/X.md")
        s.create_task("build: x", step="build", role="coder", parent=story)
        resp = self._uc(s).execute(ClaimInput(role="coder"))
        self.assertEqual(resp.spec_path, os.path.join("/specs", "specs/X.md"))


class TestBlockTask(unittest.TestCase):
    def test_routes_to_human_with_resume(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        BlockTaskUseCase(s).execute(BlockInput(task=bid, needs="decide X", branch="feat/y"))
        t = s.get_task(bid)
        self.assertEqual(t.role, "human")
        self.assertEqual(t.needs, "decide X")


class TestFlowCheck(unittest.TestCase):
    def test_returns_owner_routes_and_analysis(self):
        s = FakeStore()
        resp = FlowCheckUseCase(flow_for(METAS, s)).execute(FlowCheckInput())
        self.assertEqual(resp.owner["build"], "coder")
        self.assertEqual(resp.routes["build"], {"done": "review"})
        self.assertIn("ok", resp.analysis)
        self.assertEqual(resp.hooks, {})

    def test_hooks_surfaced_from_arbitrary_on_key(self):
        metas = {"deployer": {"model": "sonnet", "step": "deploy", "on_ship_it": True}}
        s = FakeStore()
        resp = FlowCheckUseCase(flow_for(metas, s)).execute(FlowCheckInput())
        self.assertEqual(resp.hooks, {"on_ship_it": ["deploy"]})


class TestUnblockTask(unittest.TestCase):
    def test_flips_back_to_agent_role(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="human")
        resp = UnblockTaskUseCase(s, flow_for(METAS, s)).execute(UnblockInput(task=bid))
        self.assertEqual(resp.role, "coder")
        self.assertEqual(s.get_task(bid).role, "coder")

    def test_no_agent_owner_raises(self):
        s = FakeStore()
        bid = s.create_task("a todo", role="human")
        with self.assertRaises(UseCaseError):
            UnblockTaskUseCase(s, flow_for(METAS, s)).execute(UnblockInput(task=bid))


if __name__ == "__main__":
    unittest.main()
