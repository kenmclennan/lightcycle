import unittest

from the_grid.application.errors import UseCaseError
from the_grid.application.flow import (AdvanceTask, BlockTask, ClaimTask, CompleteTask,
                                       UnblockTask)
from the_grid.application.services.flow import FlowService
from tests.fake_fs import FakeFs
from tests.fake_store import FakeStore

METAS = {
    "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
    "reviewer": {"model": "opus", "step": "review",
                 "produces": {"pr": "required"},
                 "routes": {"done": "open-pr", "rejected": "build"}},
}
SPEC_METAS = {
    "coder": {"model": "sonnet", "step": "build",
              "accepts": {"spec": "required"}, "routes": {"done": "review"}},
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

    def stamp_bead(self, spawnid, bid):
        self.stamped.append((spawnid, bid))


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
        new = AdvanceTask(s, flow_for(METAS, s)).execute(bid, "done")
        nt = s.get_task(new)
        self.assertEqual(nt.step, "review")
        self.assertEqual(nt.role, "reviewer")

    def test_unknown_outcome_returns_none(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        self.assertIsNone(AdvanceTask(s, flow_for(METAS, s)).execute(bid, "nope"))


class TestCompleteTask(unittest.TestCase):
    def test_closes_and_advances(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        new = CompleteTask(s, flow_for(METAS, s)).execute(bid, "done")
        self.assertEqual(s.get_task(bid).status, "done")
        self.assertEqual(s.get_task(new).step, "review")

    def test_invalid_outcome_raises(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        with self.assertRaises(UseCaseError):
            CompleteTask(s, flow_for(METAS, s)).execute(bid, "banana")

    def test_missing_required_output_raises(self):
        s = FakeStore()
        story = s.create_story("st")
        rid = s.create_task("review: x", step="review", role="reviewer", parent=story)
        with self.assertRaises(UseCaseError):
            CompleteTask(s, flow_for(METAS, s)).execute(rid, "done")


class TestClaimTask(unittest.TestCase):
    def _claim(self, store, config=None):
        return ClaimTask(store, flow_for(METAS, store), FakeWorktrees(),
                         FakeWorkers(), config or FakeConfig())

    def test_claims_ready_task(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        view = self._claim(s).execute("coder")
        self.assertEqual(view["id"], bid)

    def test_nothing_ready_returns_none(self):
        self.assertIsNone(self._claim(FakeStore()).execute("coder"))

    def test_stamps_spawn_id_when_present(self):
        s = FakeStore()
        s.create_task("build: x", step="build", role="coder")
        workers = FakeWorkers()
        ClaimTask(s, flow_for(METAS, s), FakeWorktrees(), workers,
                  FakeConfig(spawn="sp1")).execute("coder")
        self.assertEqual(len(workers.stamped), 1)

    def test_missing_required_input_routes_to_human(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        view = ClaimTask(s, flow_for(SPEC_METAS, s), FakeWorktrees(),
                         FakeWorkers(), FakeConfig()).execute("coder")
        self.assertIsNone(view)
        self.assertEqual(s.get_task(bid).role, "human")


class TestBlockTask(unittest.TestCase):
    def test_routes_to_human_with_resume(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="coder")
        BlockTask(s).execute(bid, "decide X", branch="feat/y")
        t = s.get_task(bid)
        self.assertEqual(t.role, "human")
        self.assertEqual(t.needs, "decide X")


class TestUnblockTask(unittest.TestCase):
    def test_flips_back_to_agent_role(self):
        s = FakeStore()
        bid = s.create_task("build: x", step="build", role="human")
        role = UnblockTask(s, flow_for(METAS, s)).execute(bid)
        self.assertEqual(role, "coder")
        self.assertEqual(s.get_task(bid).role, "coder")

    def test_no_agent_owner_raises(self):
        s = FakeStore()
        bid = s.create_task("a todo", role="human")  # no step
        with self.assertRaises(UseCaseError):
            UnblockTask(s, flow_for(METAS, s)).execute(bid)


if __name__ == "__main__":
    unittest.main()
