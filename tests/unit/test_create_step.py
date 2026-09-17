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


class _SingleOriginWFSource:
    def __init__(self, names, sha="abc"):
        self._names = names
        self._sha = sha

    def current_sha(self, origin):
        return self._sha

    def workflow_names(self, origin, sha):
        return list(self._names)

    def pinned_bundle(self, origin, sha):
        return "/bundle"


class _RefCfg:
    def default_origin(self):
        return "lightcycle"


def _flow_with_single_default_origin(store):
    metas = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
    workflow = graph_text_from_metas(metas, entry="build")
    return FlowService(
        FakeFs(metas, workflow=workflow),
        store,
        config=_RefCfg(),
        workflow_source=_SingleOriginWFSource(["standard"]),
    )


class TestCreateStepUseCase(unittest.TestCase):
    def test_role_resolves_from_the_parents_pinned_workflow(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        resp = CreateStepUseCase(s, _flow(s)).execute(
            CreateStepInput(title="", step="build", parent=parent)
        )
        step = s.get_node(resp.id)
        self.assertEqual(step.stage, "build")
        self.assertEqual(step.role, "agent")
        self.assertEqual(step.item, parent)

    def test_role_resolves_from_an_explicit_workflow(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description")
        resp = CreateStepUseCase(s, _flow(s)).execute(
            CreateStepInput(title="", step="build", parent=parent, workflow="standard")
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

    def test_a_workflow_less_parent_raises_a_clean_error_not_a_traceback(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description")
        with self.assertRaises(UseCaseError) as ctx:
            CreateStepUseCase(s, _flow_with_single_default_origin(s)).execute(
                CreateStepInput(title="", step="build", parent=parent)
            )
        self.assertIn("no workflow selected", str(ctx.exception))

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
                title="", step="build", parent=parent, note=["watch", "for", "flakes"]
            )
        )
        self.assertEqual(s.get_node(resp.id).notes, "watch for flakes")

    def test_a_note_write_failure_leaves_the_step_uncreated(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        before = dict(s._records)
        pass_before = s.current_pass(parent)

        def _boom(tid, text):
            raise RuntimeError("boom")

        s.note = _boom
        with self.assertRaises(RuntimeError):
            CreateStepUseCase(s, _flow(s)).execute(
                CreateStepInput(title="", step="build", parent=parent, note=["x"])
            )
        self.assertEqual(s._records, before)
        self.assertEqual(s.current_pass(parent), pass_before)

    def test_a_step_filed_with_no_pass_yet_open_is_enrolled_into_a_freshly_opened_pass_1(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        resp = CreateStepUseCase(s, _flow(s)).execute(
            CreateStepInput(title="", step="build", parent=parent)
        )
        current = s.current_pass(parent)
        self.assertEqual(s.get_node(resp.id).pass_id, current.id)
        self.assertEqual(current.n, 1)

    def test_a_step_filed_against_an_item_on_a_later_pass_is_enrolled_into_that_pass(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        pid1 = s.open_pass(parent)
        s.close_pass(pid1)
        pid2 = s.open_pass(parent)
        resp = CreateStepUseCase(s, _flow(s)).execute(
            CreateStepInput(title="", step="build", parent=parent)
        )
        self.assertEqual(s.get_node(resp.id).pass_id, pid2)

    def test_enrol_happens_for_an_explicit_workflow_too(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        pid1 = s.open_pass(parent)
        s.close_pass(pid1)
        pid2 = s.open_pass(parent)
        resp = CreateStepUseCase(s, _flow(s)).execute(
            CreateStepInput(title="", step="build", parent=parent, workflow="standard")
        )
        self.assertEqual(s.get_node(resp.id).pass_id, pid2)

    def test_a_title_is_refused_before_any_write(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        before = dict(s._records)
        with self.assertRaises(UseCaseError) as ctx:
            CreateStepUseCase(s, _flow(s)).execute(
                CreateStepInput(title="build it", step="build", parent=parent)
            )
        self.assertIn("title", str(ctx.exception))
        self.assertEqual(s._records, before)


if __name__ == "__main__":
    unittest.main()
