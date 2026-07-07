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
        epic = store.create_epic("e", workflow=epic_workflow)
        story = store.create_story("st", epic=epic, workflow=story_workflow)
        tid = store.create_task("build: x", step="build", parent=story)
        return store.get_task(tid)

    def test_epic_workflow_inherited_by_its_tasks(self):
        s = FakeStore()
        task = self._task_under(s, epic_workflow="poc")
        self.assertEqual(svc(s).workflow_for(task), "poc")

    def test_story_override_wins_over_epic(self):
        s = FakeStore()
        task = self._task_under(s, epic_workflow="standard", story_workflow="gherkin")
        self.assertEqual(svc(s).workflow_for(task), "gherkin")

    def test_unset_falls_back_to_default(self):
        s = FakeStore()
        task = self._task_under(s)
        self.assertEqual(svc(s).workflow_for(task), "standard")
