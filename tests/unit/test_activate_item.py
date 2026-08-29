import tempfile
import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore


def _flow(store, requires=None):
    metas = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
    workflow = graph_text_from_metas(metas, entry="build", requires=requires)
    return FlowService(FakeFs(metas, workflow=workflow), store)


class _UnresolvableFlow:
    def resolve_selection(self, selection):
        raise ValueError("origin 'ghost' has no pulled version")


class _PinnableButUnloadableFlow:
    def resolve_selection(self, selection):
        return "lightcycle/does-not-exist@testsha"

    def load_graph(self, pin):
        raise ValueError("workflow %r not found" % pin)


class TestActivateItem(unittest.TestCase):
    def test_activation_files_the_entry_step_and_flips_state(self):
        s = FakeStore()
        item = s.create_item("add refunds")
        resp = ActivateItemUseCase(s, _flow(s), None, None).execute(
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
        ActivateItemUseCase(s, _flow(s), None, None).execute(
            ActivateItemInput(item=item, workflow="standard", theme=theme)
        )
        self.assertEqual(s.get_node(item).theme, theme)

    def test_refuses_when_no_workflow_is_selected_or_inherited(self):
        s = FakeStore()
        item = s.create_item("x")
        with self.assertRaises(UseCaseError):
            ActivateItemUseCase(s, _flow(s), None, None).execute(ActivateItemInput(item=item))

    def test_refuses_to_activate_a_non_todo(self):
        s = FakeStore()
        item = s.create_item("x")
        ActivateItemUseCase(s, _flow(s), None, None).execute(
            ActivateItemInput(item=item, workflow="standard")
        )
        with self.assertRaises(UseCaseError):
            ActivateItemUseCase(s, _flow(s), None, None).execute(
                ActivateItemInput(item=item, workflow="standard")
            )

    def test_refuses_to_activate_into_a_repo_requiring_workflow_without_repo(self):
        s = FakeStore()
        item = s.create_item("add refunds")
        with self.assertRaises(UseCaseError):
            ActivateItemUseCase(s, _flow(s, requires={"repo"}), None, None).execute(
                ActivateItemInput(item=item, workflow="standard")
            )
        self.assertEqual(s.get_node(item).state, "backlogged")

    def test_activates_into_a_repo_requiring_workflow_with_repo_present(self):
        s = FakeStore()
        item = s.create_item("add refunds")
        s.add_artifact(item, "repo", "saga")
        s.add_project("acme/saga", local_path=tempfile.mkdtemp())
        resp = ActivateItemUseCase(s, _flow(s, requires={"repo"}), None, None).execute(
            ActivateItemInput(item=item, workflow="standard")
        )
        self.assertEqual(s.get_node(item).state, "ready")
        self.assertEqual(s.get_node(resp.step).step, "build")

    def test_an_unresolvable_workflow_raises_a_use_case_error_not_the_bare_value_error(self):
        s = FakeStore()
        item = s.create_item("add refunds")
        with self.assertRaises(UseCaseError):
            ActivateItemUseCase(s, _UnresolvableFlow(), None, None).execute(
                ActivateItemInput(item=item, workflow="ghost/whatever")
            )

    def test_a_pin_that_resolves_but_does_not_load_raises_before_storing_it(self):
        s = FakeStore()
        item = s.create_item("add refunds")
        with self.assertRaises(UseCaseError):
            ActivateItemUseCase(s, _PinnableButUnloadableFlow(), None, None).execute(
                ActivateItemInput(item=item, workflow="lightcycle/does-not-exist")
            )
        self.assertIsNone(s.get_node(item).workflow)

    def test_workflow_with_no_required_inputs_activates_repo_less_item(self):
        s = FakeStore()
        item = s.create_item("trend audit")
        resp = ActivateItemUseCase(s, _flow(s), None, None).execute(
            ActivateItemInput(item=item, workflow="standard")
        )
        self.assertEqual(s.get_node(item).state, "ready")
        self.assertEqual(s.get_node(resp.step).step, "build")


if __name__ == "__main__":
    unittest.main()
