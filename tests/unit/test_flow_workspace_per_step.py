import unittest

from lightcycle.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

_METAS = {
    "spec-writer": {"model": "sonnet", "step": "spec-writer", "routes": {"done": "write-code"}},
    "coder": {"model": "sonnet", "step": "write-code", "routes": {"done": "open-pr"}},
}

_UNIFIED = (
    "entry: spec-writer\n\n"
    "workspace:\n"
    "  spec-writer  specs\n\n"
    "phase:\n"
    "  spec-writer  spec\n"
    "  write-code   code\n\n"
    "edges:\n"
    "  spec-writer  done  write-code\n"
    "  write-code   done  open-pr\n"
)


def _svc(store):
    return FlowService(FakeFs(_METAS, workflow=_UNIFIED), store)


class TestWorkspacePerStep(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.item = self.store.create_item(
            "i", theme=self.store.create_theme("t"), workflow="lightcycle/spec-driven")

    def test_spec_phase_step_uses_specs_workspace(self):
        step = self.store.get_node(
            self.store.create_step("s", step="spec-writer", role="spec-writer", parent=self.item))
        self.assertEqual(_svc(self.store).workspace_for_node(step), "specs")
        self.assertEqual(_svc(self.store).phase_for(step), "spec")

    def test_code_phase_step_uses_project_workspace(self):
        step = self.store.get_node(
            self.store.create_step("w", step="write-code", role="coder", parent=self.item))
        self.assertEqual(_svc(self.store).workspace_for_node(step), "project")
        self.assertEqual(_svc(self.store).phase_for(step), "code")

    def test_item_node_falls_back_to_graph_level_default(self):
        item_node = self.store.get_node(self.item)
        self.assertEqual(_svc(self.store).workspace_for_node(item_node), "project")


if __name__ == "__main__":
    unittest.main()
