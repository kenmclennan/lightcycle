import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore


def _flow(store):
    metas = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
    return FlowService(FakeFs(metas, workflow=graph_text_from_metas(metas, entry="build")), store)


class TestActivateItem(unittest.TestCase):
    def test_activation_files_the_entry_step_and_flips_state(self):
        s = FakeStore()
        item = s.create_item("add refunds")
        resp = ActivateItemUseCase(s, _flow(s)).execute(
            ActivateItemInput(item=item, workflow="standard")
        )
        self.assertEqual(s.get_node(item).state, "ready")
        step = s.get_node(resp.step)
        self.assertEqual(step.type, "step")
        self.assertEqual(step.step, "build")
        self.assertEqual(step.role, "coder")
        self.assertEqual(step.parent, item)

    def test_activation_can_place_the_item_under_a_theme(self):
        s = FakeStore()
        theme = s.create_theme("payments")
        item = s.create_item("add refunds")
        ActivateItemUseCase(s, _flow(s)).execute(
            ActivateItemInput(item=item, workflow="standard", theme=theme)
        )
        self.assertEqual(s.get_node(item).theme, theme)

    def test_refuses_to_activate_a_non_todo(self):
        s = FakeStore()
        item = s.create_item("x")
        ActivateItemUseCase(s, _flow(s)).execute(ActivateItemInput(item=item, workflow="standard"))
        with self.assertRaises(UseCaseError):
            ActivateItemUseCase(s, _flow(s)).execute(
                ActivateItemInput(item=item, workflow="standard")
            )


if __name__ == "__main__":
    unittest.main()
