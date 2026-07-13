import unittest

from lightcycle.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs, graph_text_from_metas
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

    def test_meta_for_step_resolves_bare_human_step_by_file_not_role(self):
        metas = {
            "review-plan": {
                "step": "review-plan",
                "accepts": {"spec": "required"},
                "routes": {"approved": "build"},
            },
            "coder": {"model": "sonnet", "step": "build"},
        }
        fs = FakeFs(metas, workflow=graph_text_from_metas(metas, entry="review-plan"))
        service = FlowService(fs, FakeStore())
        self.assertEqual(service.load_flow().owner_of("review-plan"), "human")
        self.assertEqual(service.meta_for_step("review-plan"), metas["review-plan"])

    def test_ready_roles_from_store(self):
        store = FakeStore()
        store.create_step("b", step="build", role="coder")
        self.assertIn("coder", svc(store).ready_roles())


class TestPhaseFor(unittest.TestCase):
    def test_project_workspace_is_the_code_phase(self):
        store = FakeStore()
        item = store.create_item("st", theme=store.create_theme("theme"), workflow="standard")
        node = store.get_node(item)
        service = FlowService(FakeFs(METAS, workflow=graph_text_from_metas(METAS)), store)
        self.assertEqual(service.phase_for(node), "code")

    def test_specs_workspace_is_the_spec_phase(self):
        store = FakeStore()
        item = store.create_item("st", theme=store.create_theme("theme"), workflow="spec")
        node = store.get_node(item)
        fs = FakeFs(METAS, workflow="workspace: specs\n\n" + graph_text_from_metas(METAS))
        service = FlowService(fs, store)
        self.assertEqual(service.phase_for(node), "spec")


if __name__ == "__main__":
    unittest.main()
