import unittest

from lightcycle.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

METAS = {
    "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
    "reviewer": {
        "model": "opus",
        "step": "review",
        "routes": {"done": "open-pr", "rejected": "build"},
    },
}


def svc(store=None):
    return FlowService(FakeFs(METAS), store or FakeStore())


class TestFlowService(unittest.TestCase):
    def test_role_metas(self):
        self.assertEqual(svc().role_metas(), METAS)

    def test_load_flow_returns_assembled_flow(self):
        flow = svc().load_flow()
        self.assertEqual(flow.owner_of("build"), "coder")
        self.assertEqual(flow.owner_of("review"), "reviewer")
        self.assertEqual(flow.next("build", "done").to_step, "review")

    def test_flow_next_derives_owner_of_target(self):
        t = svc().flow_next("build", "done")
        self.assertEqual((t.to_step, t.to_role), ("review", "reviewer"))
        t2 = svc().flow_next("review", "rejected")
        self.assertEqual((t2.to_step, t2.to_role), ("build", "coder"))

    def test_flow_next_unknown_outcome_is_none(self):
        self.assertIsNone(svc().flow_next("build", "nope"))

    def test_meta_for_step_returns_owning_role_meta(self):
        self.assertEqual(svc().meta_for_step("build"), METAS["coder"])

    def test_meta_for_step_unowned_is_empty(self):
        self.assertEqual(svc().meta_for_step("ready-merge"), {})

    def test_ready_roles_from_store(self):
        store = FakeStore()
        store.create_step("b", step="build", role="coder")
        self.assertIn("coder", svc(store).ready_roles())


if __name__ == "__main__":
    unittest.main()
