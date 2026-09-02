import unittest

from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.planned_steps import PlannedStepsInput, PlannedStepsUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

GRAPH_TEXT = """
entry: build

nodes:
  build   coder
  review  reviewer
  audit   auditor

edges:
  build   done  review
  review  done  audit
  audit   clean
"""

METAS = {
    "coder": {"model": "sonnet"},
    "reviewer": {"model": "sonnet"},
    "auditor": {"model": "sonnet"},
}


def _uc(store):
    return PlannedStepsUseCase(store, FlowService(FakeFs(METAS, workflow=GRAPH_TEXT), store))


class TestPlannedStepsUseCase(unittest.TestCase):
    def test_projects_remaining_stages_with_ids_continuing_from_filed_count(self):
        s = FakeStore()
        item = s.create_item("st", "a description", workflow="spec-driven")
        build = s.create_step("build: x", step="build", role="agent", parent=item)
        s.close(build, "done")
        s.create_step("review: x", step="review", role="agent", parent=item)

        result = _uc(s).execute(PlannedStepsInput(item_id=item))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].step, "audit")
        self.assertEqual(result[0].role, "agent")
        self.assertEqual(result[0].id, "%s.3" % item)

    def test_terminal_step_projects_nothing(self):
        s = FakeStore()
        item = s.create_item("st", "a description", workflow="spec-driven")
        s.create_step("audit: x", step="audit", role="agent", parent=item)

        result = _uc(s).execute(PlannedStepsInput(item_id=item))

        self.assertEqual(result, [])

    def test_projected_ids_never_collide_with_a_filed_step_id(self):
        s = FakeStore()
        item = s.create_item("st", "a description", workflow="spec-driven")
        build = s.create_step("build: x", step="build", role="agent", parent=item)
        s.close(build, "done")
        review = s.create_step("review: x", step="review", role="agent", parent=item)

        result = _uc(s).execute(PlannedStepsInput(item_id=item))

        filed_ids = {build, review}
        self.assertFalse(any(p.id in filed_ids for p in result))

    def test_no_live_step_returns_empty_when_not_yet_activated(self):
        s = FakeStore()
        item = s.create_item("st", "a description", workflow="spec-driven")

        result = _uc(s).execute(PlannedStepsInput(item_id=item))

        self.assertEqual(result, [])

    def test_no_live_step_returns_empty_after_terminal_close(self):
        s = FakeStore()
        item = s.create_item("st", "a description", workflow="spec-driven")
        audit = s.create_step("audit: x", step="audit", role="agent", parent=item)
        s.close(audit, "clean")

        result = _uc(s).execute(PlannedStepsInput(item_id=item))

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
