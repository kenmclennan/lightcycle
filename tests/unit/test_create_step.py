import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.create_step import CreateStepInput, CreateStepUseCase
from lightcycle.application.work.item_outputs import ItemOutputs
from lightcycle.application.work.step_inputs import StepInputs
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore
from pathlib import Path

from lightcycle.domain.flow.graph import parse_graph
from tests.support.fake_workers import FakeWorkers


class _Config:
    def max_title_length(self):
        return 80


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

    def prompts_root(self):
        return "/prompts"


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
    def test_closed_parent_refuses_and_creates_no_step_until_reopened(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        s.complete_node(parent, "done")
        use_case = CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers())
        with self.assertRaises(UseCaseError) as ctx:
            use_case.execute(CreateStepInput(title="", step="build", parent=parent))
        self.assertEqual(
            str(ctx.exception),
            "item %s is closed; use lc reopen %s to bring it back" % (parent, parent),
        )
        self.assertEqual(list(s.all_steps_including_done()), [])
        s.reopen(parent)
        resp = use_case.execute(CreateStepInput(title="", step="build", parent=parent))
        self.assertEqual(s.get_node(resp.id).item, parent)

    def test_role_resolves_from_the_parents_pinned_workflow(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        resp = CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
            CreateStepInput(title="", step="build", parent=parent)
        )
        step = s.get_node(resp.id)
        self.assertEqual(step.stage, "build")
        self.assertEqual(step.role, "agent")
        self.assertEqual(step.item, parent)

    def test_role_resolves_from_an_explicit_workflow(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description")
        resp = CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
            CreateStepInput(title="", step="build", parent=parent, workflow="standard")
        )
        self.assertEqual(s.get_node(resp.id).role, "agent")

    def test_unknown_step_name_raises_listing_owned_steps(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        with self.assertRaises(UseCaseError) as ctx:
            CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
                CreateStepInput(title="build it", step="not-a-real-step", parent=parent)
            )
        self.assertIn("build", str(ctx.exception))

    def test_an_over_length_title_is_refused_before_the_non_blank_title_refusal(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        with self.assertRaises(UseCaseError) as ctx:
            CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
                CreateStepInput(title="x" * 81, step="build", parent=parent)
            )
        self.assertIn("title exceeds 80 chars", str(ctx.exception))

    def test_a_workflow_less_parent_raises_a_clean_error_not_a_traceback(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description")
        with self.assertRaises(UseCaseError) as ctx:
            CreateStepUseCase(s, _flow_with_single_default_origin(s), _Config(), FakeWorkers()).execute(
                CreateStepInput(title="", step="build", parent=parent)
            )
        self.assertIn("no workflow selected", str(ctx.exception))

    def test_unknown_parent_raises(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError) as ctx:
            CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
                CreateStepInput(title="build it", step="build", parent="does-not-exist")
            )
        self.assertIn("does-not-exist", str(ctx.exception))

    def test_note_is_written_when_given(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        resp = CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
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
            CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
                CreateStepInput(title="", step="build", parent=parent, note=["x"])
            )
        self.assertEqual(s._records, before)
        self.assertEqual(s.current_pass(parent), pass_before)

    def test_a_step_filed_with_no_pass_yet_open_is_enrolled_into_a_freshly_opened_pass_1(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        resp = CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
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
        resp = CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
            CreateStepInput(title="", step="build", parent=parent)
        )
        self.assertEqual(s.get_node(resp.id).pass_id, pid2)

    def test_enrol_happens_for_an_explicit_workflow_too(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        pid1 = s.open_pass(parent)
        s.close_pass(pid1)
        pid2 = s.open_pass(parent)
        resp = CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
            CreateStepInput(title="", step="build", parent=parent, workflow="standard")
        )
        self.assertEqual(s.get_node(resp.id).pass_id, pid2)

    def test_a_title_is_refused_before_any_write(self):
        s = FakeStore()
        parent = s.create_item("an item", "a description", workflow="standard")
        before = dict(s._records)
        with self.assertRaises(UseCaseError) as ctx:
            CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
                CreateStepInput(title="build it", step="build", parent=parent)
            )
        self.assertIn("title", str(ctx.exception))
        self.assertEqual(s._records, before)


if __name__ == "__main__":
    unittest.main()


def _tick_clock():
    state = {"n": 0}

    def now():
        state["n"] += 1
        return "2026-01-01T00:00:%02d+00:00" % state["n"]

    return now


def _closed_step(s, parent, report):
    tid = s.create_step(stage="build", role="agent", item=parent)
    s.set_report(tid, report)
    s.complete_node(tid, "done")
    return tid


def _build(s, flow, step_id):
    return StepInputs(s, flow, ItemOutputs(s, flow)).build(s.get_node(step_id))


class TestCreateStepPrevious(unittest.TestCase):
    def test_a_re_armed_step_carries_the_last_closed_steps_report_and_the_note(self):
        s = FakeStore(now=_tick_clock())
        flow = _flow(s)
        parent = s.create_item("an item", "a description", workflow="standard")
        closed = _closed_step(s, parent, "ci failed: test_x")
        self.assertTrue(s.get_node(closed).report)
        resp = CreateStepUseCase(s, flow, _Config(), FakeWorkers()).execute(
            CreateStepInput(title="", step="build", parent=parent, note=["try the other layer"])
        )
        self.assertEqual(s.get_node(resp.id).previous_step, closed)
        built = _build(s, flow, resp.id)
        self.assertEqual(built["previous"]["report"], "ci failed: test_x")
        self.assertEqual(built["previous"]["step"], closed)
        self.assertEqual(built["previous"]["stage"], s.get_node(closed).stage)
        self.assertIn("try the other layer", s.get_node(resp.id).notes)

    def test_the_latest_closed_step_wins_when_closing_order_differs_from_creation_order(self):
        s = FakeStore(now=_tick_clock())
        parent = s.create_item("an item", "a description", workflow="standard")
        earlier_created = s.create_step(stage="build", role="agent", item=parent)
        later_created = s.create_step(stage="build", role="agent", item=parent)
        s.complete_node(later_created, "done")
        s.complete_node(earlier_created, "done")
        resp = CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
            CreateStepInput(title="", step="build", parent=parent)
        )
        self.assertEqual(s.get_node(resp.id).previous_step, earlier_created)

    def test_equal_closed_at_prefers_the_later_created_step(self):
        s = FakeStore(now=_tick_clock())
        parent = s.create_item("an item", "a description", workflow="standard")
        first = s.create_step(stage="build", role="agent", item=parent)
        second = s.create_step(stage="build", role="agent", item=parent)
        s.complete_node(first, "done")
        s.complete_node(second, "done")
        for tid in (first, second):
            s._records[tid]["closed_at"] = "2026-01-01T00:01:00+00:00"
        resp = CreateStepUseCase(s, _flow(s), _Config(), FakeWorkers()).execute(
            CreateStepInput(title="", step="build", parent=parent)
        )
        self.assertEqual(s.get_node(resp.id).previous_step, second)

    def test_no_closed_step_leaves_previous_empty(self):
        s = FakeStore(now=_tick_clock())
        flow = _flow(s)
        parent = s.create_item("an item", "a description", workflow="standard")
        open_step = s.create_step(stage="build", role="agent", item=parent)
        resp = CreateStepUseCase(s, flow, _Config(), FakeWorkers()).execute(
            CreateStepInput(title="", step="build", parent=parent, replace=open_step)
        )
        self.assertIsNone(s.get_node(resp.id).previous_step)
        self.assertIsNone(_build(s, flow, resp.id)["previous"])


_PHASED = {
    "cutter": {"step": "cut-delivery", "phase": "code", "routes": {"done": "write-code"}},
    "coder": {"step": "write-code", "phase": "code", "routes": {"done": "merge"}},
    "feedback": {"step": "handle-feedback", "phase": "code"},
}


def _phased_flow(store):
    workflow = graph_text_from_metas(_PHASED, entry="cut-delivery")
    return FlowService(FakeFs(_PHASED, workflow=workflow), store)


def _guarded(workers=None):
    s = FakeStore(now=_tick_clock())
    parent = s.create_item("an item", "a description", workflow="standard")
    use_case = CreateStepUseCase(s, _phased_flow(s), _Config(), workers or FakeWorkers())
    return s, parent, use_case


def _file(use_case, parent, step, **kw):
    return use_case.execute(CreateStepInput(title="", step=step, parent=parent, **kw))


class TestForkGuard(unittest.TestCase):
    def test_a_second_main_path_step_in_the_phase_is_refused_and_nothing_is_stored(self):
        s, parent, use_case = _guarded()
        open_step = s.create_step(stage="cut-delivery", role="cutter", item=parent)
        self.assertIn(open_step, [t.id for t in s.all_steps_including_done()])
        before = dict(s._records)
        with self.assertRaises(UseCaseError) as ctx:
            _file(use_case, parent, "write-code")
        msg = str(ctx.exception)
        for part in (open_step, "cut-delivery", "phase code", "lc rm", "lc done", "--replace"):
            self.assertIn(part, msg)
        self.assertEqual(dict(s._records), before)

    def test_an_off_path_step_is_allowed_beside_an_open_main_path_step(self):
        s, parent, use_case = _guarded()
        s.create_step(stage="cut-delivery", role="cutter", item=parent)
        resp = _file(use_case, parent, "handle-feedback")
        self.assertEqual(s.get_node(resp.id).stage, "handle-feedback")

    def test_a_main_path_step_is_allowed_when_none_is_open_in_its_phase(self):
        s, parent, use_case = _guarded()
        self.assertTrue(_file(use_case, parent, "write-code").id)
        s2, parent2, use_case2 = _guarded()
        closed = s2.create_step(stage="cut-delivery", role="cutter", item=parent2)
        s2.complete_node(closed, "done")
        self.assertTrue(_file(use_case2, parent2, "write-code").id)

    def test_a_pre_existing_fork_between_other_steps_does_not_block_an_off_path_step(self):
        s, parent, use_case = _guarded()
        s.create_step(stage="cut-delivery", role="cutter", item=parent)
        s.create_step(stage="write-code", role="coder", item=parent)
        self.assertTrue(_file(use_case, parent, "handle-feedback").id)

    def test_guard_agrees_with_the_doctors_forks_on_the_committed_spec_driven_graph(self):
        text = Path("tests/support/library/workflows/spec-driven.md").read_text()
        graph = parse_graph(text)

        class _Flow:
            def __init__(self, inner):
                self._inner = inner

            def graph_for(self, node):
                return graph

            def __getattr__(self, name):
                return getattr(self._inner, name)

        metas = {"coder": {"step": "write-code", "routes": {"done": "watch-ci"}}}
        inner = FlowService(
            FakeFs(metas, workflow=graph_text_from_metas(metas, entry="write-code")),
            FakeStore(),
        )
        node_store = FakeStore()
        parent = node_store.create_item("an item", "a description", workflow="standard")
        node_store.create_step(stage="watch-ci", role="agent", item=parent)
        use_case = CreateStepUseCase(
            node_store, _Flow(inner), _Config(), FakeWorkers()
        )
        before = dict(node_store._records)
        with self.assertRaises(UseCaseError):
            _file(use_case, parent, "write-code")
        self.assertEqual(dict(node_store._records), before)


class TestReplace(unittest.TestCase):
    def test_replace_removes_the_named_open_step_and_files_the_new_one_together(self):
        s, parent, use_case = _guarded()
        old = s.create_step(stage="cut-delivery", role="cutter", item=parent)
        self.assertIn(old, [t.id for t in s.all_steps_including_done()])
        resp = _file(use_case, parent, "write-code", replace=old)
        ids = [t.id for t in s.all_steps_including_done()]
        self.assertNotIn(old, ids)
        self.assertIn(resp.id, ids)
        self.assertEqual(s.get_node(resp.id).pass_id, s.current_pass(parent).id)

    def test_replace_rolls_back_the_delete_when_filing_fails(self):
        s, parent, use_case = _guarded()
        old = s.create_step(stage="cut-delivery", role="cutter", item=parent)

        def boom(*a, **k):
            raise RuntimeError("note write failed")

        s.note = boom
        with self.assertRaises(RuntimeError):
            _file(use_case, parent, "write-code", note=["x"], replace=old)
        self.assertIn(old, [t.id for t in s.all_steps_including_done()])

    def test_replace_refuses_an_unknown_other_item_closed_or_live_claimed_step(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "sp1", "pid": 7, "started": 1, "step": None}],
            alive_pids=(7,),
        )
        s, parent, use_case = _guarded(workers)
        other = s.create_item("another", "a description", workflow="standard")
        foreign = s.create_step(stage="cut-delivery", role="cutter", item=other)
        closed = s.create_step(stage="cut-delivery", role="cutter", item=parent)
        s.complete_node(closed, "done")
        live = s.create_step(stage="cut-delivery", role="cutter", item=parent)
        s.claim_ready("cutter", "sp1", item=parent)
        workers.seed([{"spawnid": "sp1", "pid": 7, "started": 1, "step": live}])
        for target, needle in (
            ("NOPE-1", "no such step"),
            (foreign, "belongs to item"),
            (closed, "already closed"),
            (live, "claimed by a live worker"),
        ):
            before = dict(s._records)
            with self.assertRaises(UseCaseError) as ctx:
                _file(use_case, parent, "write-code", replace=target)
            self.assertIn(needle, str(ctx.exception))
            self.assertEqual(dict(s._records), before)

    def test_replace_of_a_step_that_is_not_the_fork_cause_is_refused_and_removes_nothing(self):
        s, parent, use_case = _guarded()
        a = s.create_step(stage="cut-delivery", role="cutter", item=parent)
        b = s.create_step(stage="write-code", role="coder", item=parent)
        off = s.create_step(stage="handle-feedback", role="feedback", item=parent)
        with self.assertRaises(UseCaseError):
            _file(use_case, parent, "write-code", replace=off)
        ids = [t.id for t in s.all_steps_including_done()]
        for kept in (a, b, off):
            self.assertIn(kept, ids)
