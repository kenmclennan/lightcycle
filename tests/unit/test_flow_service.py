import unittest

from the_grid.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

METAS = {
    "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
    "reviewer": {"model": "opus", "step": "review",
                 "routes": {"done": "open-pr", "rejected": "build"}},
}


def svc(store=None):
    return FlowService(FakeFs(METAS), store or FakeStore())


class TestFlowService(unittest.TestCase):
    def test_role_metas(self):
        self.assertEqual(svc().role_metas(), METAS)

    def test_load_flow_owner_and_routes(self):
        owner, routes = svc().load_flow()
        self.assertEqual(owner["build"], "coder")
        self.assertEqual(owner["review"], "reviewer")
        self.assertEqual(routes["build"], {"done": "review"})

    def test_flow_next_derives_owner_of_target(self):
        self.assertEqual(svc().flow_next("build", "done"), ("review", "reviewer"))
        self.assertEqual(svc().flow_next("review", "rejected"), ("build", "coder"))

    def test_flow_next_unknown_outcome_is_none(self):
        self.assertIsNone(svc().flow_next("build", "nope"))

    def test_meta_for_step_returns_owning_role_meta(self):
        self.assertEqual(svc().meta_for_step("build"), METAS["coder"])

    def test_meta_for_step_unowned_is_empty(self):
        self.assertEqual(svc().meta_for_step("ready-merge"), {})

    def test_ready_roles_from_store(self):
        store = FakeStore()
        store.create_task("b", step="build", role="coder")
        self.assertIn("coder", svc(store).ready_roles())


if __name__ == "__main__":
    unittest.main()
