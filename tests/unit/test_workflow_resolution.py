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
    def _task_under(self, store, *, epic_workflow=None, story_workflow=None):
        theme = store.create_theme("e", workflow=epic_workflow)
        item = store.create_item("st", theme=theme, workflow=story_workflow)
        tid = store.create_step("build: x", step="build", parent=item)
        return store.get_node(tid)

    def test_epic_workflow_inherited_by_its_tasks(self):
        s = FakeStore()
        step = self._task_under(s, epic_workflow="poc")
        self.assertEqual(svc(s).workflow_for(step), "poc")

    def test_story_override_wins_over_epic(self):
        s = FakeStore()
        step = self._task_under(s, epic_workflow="standard", story_workflow="gherkin")
        self.assertEqual(svc(s).workflow_for(step), "gherkin")

    def test_unset_returns_none_when_no_ancestor_sets_it(self):
        s = FakeStore()
        step = self._task_under(s)
        self.assertIsNone(svc(s).workflow_for(step))
