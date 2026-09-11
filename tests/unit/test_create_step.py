import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.create_step import CreateStepInput, CreateStepUseCase
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore


def _flow(store, requires=None):
    metas = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
    workflow = graph_text_from_metas(metas, entry="build", requires=requires)
    return FlowService(FakeFs(metas, workflow=workflow), store)


class TestCreateStepUseCase(unittest.TestCase):
    def test_role_resolves_from_the_parents_pinned_workflow(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        resp = CreateStepUseCase(s, _flow(s)).execute(
            CreateStepInput(title="build it", step="build", parent=parent)
        )
        step = s.get_node(resp.id)
        self.assertEqual(step.stage, "build")
        self.assertEqual(step.role, "agent")
        self.assertEqual(step.item, parent)

    def test_role_resolves_from_an_explicit_workflow(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description")
        resp = CreateStepUseCase(s, _flow(s)).execute(
            CreateStepInput(title="build it", step="build", parent=parent, workflow="standard")
        )
        self.assertEqual(s.get_node(resp.id).role, "agent")

    def test_unknown_step_name_raises_listing_owned_steps(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        with self.assertRaises(UseCaseError) as ctx:
            CreateStepUseCase(s, _flow(s)).execute(
                CreateStepInput(title="build it", step="not-a-real-step", parent=parent)
            )
        self.assertIn("build", str(ctx.exception))

    def test_unknown_parent_raises(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError) as ctx:
            CreateStepUseCase(s, _flow(s)).execute(
                CreateStepInput(title="build it", step="build", parent="does-not-exist")
            )
        self.assertIn("does-not-exist", str(ctx.exception))

    def test_note_is_written_when_given(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        resp = CreateStepUseCase(s, _flow(s)).execute(
            CreateStepInput(
                title="build it", step="build", parent=parent, note=["watch", "for", "flakes"]
            )
        )
        self.assertEqual(s.get_node(resp.id).notes, "watch for flakes")

    def test_a_note_write_failure_leaves_the_step_uncreated(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        before = dict(s._records)

        def _boom(tid, text):
            raise RuntimeError("boom")

        s.note = _boom
        with self.assertRaises(RuntimeError):
            CreateStepUseCase(s, _flow(s)).execute(
                CreateStepInput(title="build it", step="build", parent=parent, note=["x"])
            )
        self.assertEqual(s._records, before)


if __name__ == "__main__":
    unittest.main()
