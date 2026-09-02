import unittest

from lightcycle.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


class _Cfg:
    def default_workflow(self):
        return "standard"

    def default_workflow_for(self, project):
        return "standard"


def svc(store):
    return FlowService(FakeFs({}), store, _Cfg())


class TestWorkflowFor(unittest.TestCase):
    def _task_under(self, store, *, item_workflow=None, step_workflow=None):
        item = store.create_item("st", workflow=item_workflow)
        tid = store.create_step("build: x", step="build", parent=item)
        if step_workflow is not None:
            store.edit_node(tid, workflow=step_workflow)
        return store.get_node(tid)

    def test_item_workflow_inherited_by_its_steps(self):
        s = FakeStore()
        step = self._task_under(s, item_workflow="poc")
        self.assertEqual(svc(s).workflow_for(step), "poc")

    def test_step_override_wins_over_its_item(self):
        s = FakeStore()
        step = self._task_under(s, item_workflow="standard", step_workflow="gherkin")
        self.assertEqual(svc(s).workflow_for(step), "gherkin")

    def test_unset_returns_none_when_no_ancestor_sets_it(self):
        s = FakeStore()
        step = self._task_under(s)
        self.assertIsNone(svc(s).workflow_for(step))


class TestWorkflowOwner(unittest.TestCase):
    def _task_under(self, store, *, item_workflow=None, step_workflow=None):
        item = store.create_item("st", workflow=item_workflow)
        tid = store.create_step("build: x", step="build", parent=item)
        if step_workflow is not None:
            store.edit_node(tid, workflow=step_workflow)
        return store.get_node(tid), item

    def test_inherited_from_the_item_reports_the_item_as_owner(self):
        s = FakeStore()
        step, item = self._task_under(s, item_workflow="poc")
        self.assertEqual(svc(s).workflow_owner(step), ("poc", item))

    def test_a_steps_own_workflow_reports_the_step_as_owner(self):
        s = FakeStore()
        step, _item = self._task_under(s, item_workflow="standard", step_workflow="gherkin")
        self.assertEqual(svc(s).workflow_owner(step), ("gherkin", step.id))

    def test_unset_returns_no_selector_and_no_owner(self):
        s = FakeStore()
        step, _item = self._task_under(s)
        self.assertEqual(svc(s).workflow_owner(step), (None, None))
