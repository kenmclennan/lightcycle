import os
import tempfile
import unittest

from lightcycle.application.work import (
    ActiveStepsUseCase,
    BacklogInput,
    BacklogUseCase,
    InboxInput,
    InboxUseCase,
    QueueInput,
    QueueUseCase,
    ShowNodeInput,
    ShowNodeUseCase,
    StatusUseCase,
    TraceInput,
    TraceUseCase,
)
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.project_of import short_project_label
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.fake_store import FakeStore


def _empty_flow(store):
    return FlowService(FakeFs({}), store)


def _flow_with_step(store, step_name):
    return FlowService(FakeFs({"some-role": {"step": step_name}}), store)


class _Workers:
    def __init__(self, workers=None):
        self._workers = workers or []

    def workers_state(self):
        return self._workers


class _Config:
    def __init__(self, root="/grid"):
        self._root = root

    def data_root(self):
        return self._root


class TestShowNode(unittest.TestCase):
    def test_returns_task_view(self):
        s = FakeStore()
        tid = s.create_step("build: x", step="build", role="coder")
        view = ShowNodeUseCase(s).execute(ShowNodeInput(step=tid)).view
        self.assertEqual(view.step.id, tid)
        self.assertEqual(view.step.title, "build: x")
        self.assertIn("item_artifacts", view.as_dict())


class TestTrace(unittest.TestCase):
    def test_assembles_story_artifacts_tasks_and_logs(self):
        s = FakeStore()
        sid = s.create_item("st", theme=s.create_theme("theme"))
        s.add_artifact(sid, "spec", "specs/x.md")
        k = s.create_step("build: x", step="build", role="coder", parent=sid)
        workers = _Workers([{"role": "coder", "step": k, "log": "/l/k.log"}])
        resp = TraceUseCase(s, workers, _Config()).execute(TraceInput(item=sid))
        self.assertEqual(resp.item.id, sid)
        self.assertEqual(resp.artifacts[0].type, "spec")
        self.assertEqual(resp.steps[0].id, k)
        self.assertEqual(resp.steps[0].log, "/l/k.log")

    def test_step_role_survives_to_the_trace(self):
        s = FakeStore()
        sid = s.create_item("st", theme=s.create_theme("theme"))
        s.create_step("build: x", step="build", role="coder", parent=sid)
        resp = TraceUseCase(s, _Workers([]), _Config()).execute(TraceInput(item=sid))
        self.assertEqual(resp.steps[0].role, "coder")

    def test_human_role_survives_to_the_trace_unchanged(self):
        s = FakeStore()
        sid = s.create_item("st", theme=s.create_theme("theme"))
        s.create_step("ready-merge: x", step="ready-merge", role="human", parent=sid)
        resp = TraceUseCase(s, _Workers([]), _Config()).execute(TraceInput(item=sid))
        self.assertEqual(resp.steps[0].role, "human")

    def test_resolves_log_from_disk_when_registry_entry_is_pruned(self):
        s = FakeStore()
        sid = s.create_item("st", theme=s.create_theme("theme"))
        k = s.create_step("build: x", step="build", role="coder", parent=sid)
        s.assign(k, "sp1")
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "logs"))
        log_path = os.path.join(root, "logs", "worker-coder-sp1.log")
        with open(log_path, "w") as f:
            f.write("log\n")
        resp = TraceUseCase(s, _Workers([]), _Config(root=root)).execute(TraceInput(item=sid))
        self.assertEqual(resp.steps[0].log, log_path)

    def test_resolves_no_log_when_pruned_and_nothing_on_disk(self):
        s = FakeStore()
        sid = s.create_item("st", theme=s.create_theme("theme"))
        k = s.create_step("build: x", step="build", role="coder", parent=sid)
        s.assign(k, "sp1")
        root = tempfile.mkdtemp()
        resp = TraceUseCase(s, _Workers([]), _Config(root=root)).execute(TraceInput(item=sid))
        self.assertIsNone(resp.steps[0].log)

    def test_resolves_no_log_for_a_step_never_claimed(self):
        s = FakeStore()
        sid = s.create_item("st", theme=s.create_theme("theme"))
        s.create_step("build: x", step="build", role="coder", parent=sid)
        root = tempfile.mkdtemp()
        resp = TraceUseCase(s, _Workers([]), _Config(root=root)).execute(TraceInput(item=sid))
        self.assertIsNone(resp.steps[0].log)


def _seed_mixed_store():
    s = FakeStore()
    todo_item = s.create_item("todo item")
    active_item = s.create_item("active item")
    theme = s.create_theme("a theme")
    ready = s.create_step("ready one", step="build", role="coder")
    human = s.create_step("needs me", role="human")
    running = s.create_step("running", step="build", role="coder")
    s.assign(running, "worker-1")
    non_steps = [todo_item, active_item, theme]
    return s, non_steps, {"ready": ready, "human": human, "running": running}


class TestStatus(unittest.TestCase):
    def test_lanes_tasks_by_status(self):
        s = FakeStore()
        ready = s.create_step("ready one", step="build", role="coder")
        human = s.create_step("needs me", role="human")
        running = s.create_step("running", step="build", role="coder")
        s.assign(running, "worker-1")
        lanes = StatusUseCase(s).execute().lanes
        self.assertEqual([t.id for t in lanes["queue"]], [ready])
        self.assertEqual([t.id for t in lanes["inbox"]], [human])
        self.assertEqual([t.id for t in lanes["active"]], [running])

    def test_watched_step_leaves_the_inbox_lane_while_its_feedback_step_is_open(self):
        s = FakeStore()
        watched = s.create_step("await-merge: thing", step="await-merge", role="human")
        fb = s.create_step("handle feedback", step="handle-feedback", role="handle-feedback",
                           parent=s.get_node(watched).parent)
        s.add_artifact(fb, "watched-step", watched)

        lanes = StatusUseCase(s).execute().lanes

        self.assertNotIn(watched, [t.id for t in lanes["inbox"]])

    def test_watched_step_returns_to_the_inbox_lane_once_its_feedback_step_closes(self):
        s = FakeStore()
        watched = s.create_step("await-merge: thing", step="await-merge", role="human")
        fb = s.create_step("handle feedback", step="handle-feedback", role="handle-feedback",
                           parent=s.get_node(watched).parent)
        s.add_artifact(fb, "watched-step", watched)
        s.close(fb, "done")

        lanes = StatusUseCase(s).execute().lanes

        self.assertIn(watched, [t.id for t in lanes["inbox"]])

    def test_dep_blocked_task_lands_in_queue(self):
        s = FakeStore()
        blocker = s.create_step("blocker", step="build", role="coder")
        blocked = s.create_step("blocked", step="build", role="coder", deps=[blocker])
        lanes = StatusUseCase(s).execute().lanes
        self.assertIn(blocked, [t.id for t in lanes["queue"]])
        self.assertNotIn("blocked", lanes)

    def test_lanes_contain_only_steps_never_items_or_themes(self):
        s, non_steps, steps = _seed_mixed_store()
        lanes = StatusUseCase(s).execute().lanes
        self.assertEqual([t.id for t in lanes["queue"]], [steps["ready"]])
        self.assertEqual([t.id for t in lanes["inbox"]], [steps["human"]])
        self.assertEqual([t.id for t in lanes["active"]], [steps["running"]])
        all_lane_ids = {t.id for lane in lanes.values() for t in lane}
        for non_step in non_steps:
            self.assertNotIn(non_step, all_lane_ids)


class TestActiveTasks(unittest.TestCase):
    def test_returns_only_in_progress(self):
        s = FakeStore()
        s.create_step("waiting", step="build", role="coder")
        running = s.create_step("running", step="build", role="coder")
        s.assign(running, "worker-1")
        self.assertEqual([t.id for t in ActiveStepsUseCase(s).execute().steps], [running])

    def test_active_contains_only_steps_never_items_or_themes(self):
        s, non_steps, steps = _seed_mixed_store()
        result_ids = [t.id for t in ActiveStepsUseCase(s).execute().steps]
        self.assertEqual(result_ids, [steps["running"]])
        for non_step in non_steps:
            self.assertNotIn(non_step, result_ids)


class TestQueue(unittest.TestCase):
    def test_lists_ready_capped_at_n(self):
        s = FakeStore()
        ids = [s.create_step("t%d" % i, step="build", role="coder") for i in range(3)]
        out = QueueUseCase(s).execute(QueueInput(n=2)).steps
        self.assertEqual(len(out), 2)
        self.assertTrue(set(t.id for t in out).issubset(set(ids)))

    def test_default_n_is_ten(self):
        s = FakeStore()
        for i in range(12):
            s.create_step("t%d" % i, step="build", role="coder")
        self.assertEqual(len(QueueUseCase(s).execute(QueueInput()).steps), 10)

    def test_queue_contains_only_steps_never_items_or_themes(self):
        s, non_steps, steps = _seed_mixed_store()
        result_ids = [t.id for t in QueueUseCase(s).execute(QueueInput()).steps]
        self.assertEqual(result_ids, [steps["ready"]])
        for non_step in non_steps:
            self.assertNotIn(non_step, result_ids)


class TestInboxPerItemWorkflow(unittest.TestCase):
    def test_each_human_step_is_classified_against_its_own_workflow(self):
        s = FakeStore()
        a_metas = {"gate": {"step": "gate", "routes": {"approve": "done", "reject": "build"}}}
        b_metas = {"gate": {"step": "gate", "routes": {"merge": "done"}}}
        fs = FakeFs(a_metas, workflows={
            "wfA": graph_text_from_metas(a_metas),
            "wfB": graph_text_from_metas(b_metas),
        })
        flow_svc = FlowService(fs, s)
        item_a = s.create_item("iA", theme=s.create_theme("A"), workflow="wfA")
        a = s.create_step("gate: A", step="gate", role="human", parent=item_a)
        item_b = s.create_item("iB", theme=s.create_theme("B"), workflow="wfB")
        b = s.create_step("gate: B", step="gate", role="human", parent=item_b)
        rows = InboxUseCase(s, flow_svc).execute(InboxInput()).rows
        outcomes = {row.step.id: row.outcomes for row in rows}
        self.assertEqual(outcomes[a], ["approve", "reject"])
        self.assertEqual(outcomes[b], ["merge"])


class TestInboxBacklog(unittest.TestCase):
    def _store(self):
        s = FakeStore()
        self.todo = s.create_item("todo item")
        self.gate = s.create_step("a gate", step="review", role="human")
        return s

    def test_inbox_has_stepped_human_tasks_not_todos(self):
        s = self._store()
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput())
        ids = [row.step.id for row in resp.rows]
        self.assertIn(self.gate, ids)
        self.assertNotIn(self.todo, ids)

    def test_backlog_has_todos_not_stepped(self):
        s = self._store()
        ids = [
            row.step.id for row in BacklogUseCase(s, _empty_flow(s)).execute(BacklogInput()).rows
        ]
        self.assertIn(self.todo, ids)
        self.assertNotIn(self.gate, ids)

    def test_todo_item_in_backlog_appears_in_no_status_lane(self):
        s = self._store()
        backlog_ids = [
            row.step.id for row in BacklogUseCase(s, _empty_flow(s)).execute(BacklogInput()).rows
        ]
        self.assertIn(self.todo, backlog_ids)
        lanes = StatusUseCase(s).execute().lanes
        lane_ids = {t.id for lane in lanes.values() for t in lane}
        self.assertNotIn(self.todo, lane_ids)


class TestInboxNoCandidateThemes(unittest.TestCase):
    def test_all_closed_stories_epic_never_surfaces_in_inbox(self):
        s = FakeStore()
        theme = s.create_theme("My Epic")
        s.close(s.create_item("item 1", theme=theme), "done")
        s.close(s.create_item("item 2", theme=theme), "done")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput())
        self.assertNotIn(theme, [row.step.id for row in resp.rows])


class TestInboxAttentionFlag(unittest.TestCase):
    def test_flagged_task_appears_in_inbox_as_triage(self):
        s = FakeStore()
        tid = s.create_step("urgent finding", role="human", attention=True)
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput())
        ids = [row.step.id for row in resp.rows]
        kinds = {row.step.id: row.kind for row in resp.rows}
        self.assertIn(tid, ids)
        self.assertEqual(kinds[tid], "triage")

    def test_unflagged_task_absent_from_inbox(self):
        s = FakeStore()
        tid = s.create_step("someday idea", role="human")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput())
        self.assertNotIn(tid, [row.step.id for row in resp.rows])

    def test_closing_flagged_task_removes_it_from_inbox(self):
        s = FakeStore()
        tid = s.create_step("urgent finding", role="human", attention=True)
        s.close(tid, "done")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput())
        self.assertNotIn(tid, [row.step.id for row in resp.rows])

    def test_flagged_task_title_accessible_via_row(self):
        s = FakeStore()
        tid = s.create_step("audit: spec gaps", role="human", attention=True)
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput())
        row = next(r for r in resp.rows if r.step.id == tid)
        self.assertEqual(row.step.title, "audit: spec gaps")


class TestInboxProjectAndPr(unittest.TestCase):
    def _item_with_step(self, s, step_name="ready-merge", repo=None, pr=None):
        item = s.create_item("an item")
        if repo:
            s.add_artifact(item, "repo", repo)
        if pr:
            s.add_artifact(item, "pr", pr)
        tid = s.create_step("a gate", step=step_name, role="human", parent=item)
        return item, tid

    def test_service_step_with_human_role_is_an_action_not_blocked(self):
        s = FakeStore()
        _, tid = self._item_with_step(s, step_name="review-findings")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput())
        row = next(r for r in resp.rows if r.step.id == tid)
        self.assertEqual(row.kind, "action")

    def test_row_project_from_item_repo_artifact(self):
        s = FakeStore()
        _, tid = self._item_with_step(s, repo="proj-a")
        resp = InboxUseCase(s, _flow_with_step(s, "ready-merge")).execute(InboxInput())
        row = next(r for r in resp.rows if r.step.id == tid)
        self.assertEqual(row.project, "proj-a")

    def test_row_project_none_when_item_has_no_repo_artifact(self):
        s = FakeStore()
        _, tid = self._item_with_step(s)
        resp = InboxUseCase(s, _flow_with_step(s, "ready-merge")).execute(InboxInput())
        row = next(r for r in resp.rows if r.step.id == tid)
        self.assertIsNone(row.project)

    def test_row_pr_from_item_pr_artifact(self):
        s = FakeStore()
        _, tid = self._item_with_step(s, pr="https://example.com/pr/9")
        resp = InboxUseCase(s, _flow_with_step(s, "ready-merge")).execute(InboxInput())
        row = next(r for r in resp.rows if r.step.id == tid)
        self.assertEqual(row.pr, "https://example.com/pr/9")

    def test_row_pr_none_when_item_has_no_pr_artifact(self):
        s = FakeStore()
        _, tid = self._item_with_step(s)
        resp = InboxUseCase(s, _flow_with_step(s, "ready-merge")).execute(InboxInput())
        row = next(r for r in resp.rows if r.step.id == tid)
        self.assertIsNone(row.pr)

    def test_pr_resolves_regardless_of_step_name(self):
        s = FakeStore()
        _, tid = self._item_with_step(
            s, step_name="totally-arbitrary-step-name", pr="https://example.com/pr/3"
        )
        resp = InboxUseCase(s, _flow_with_step(s, "totally-arbitrary-step-name")).execute(
            InboxInput()
        )
        row = next(r for r in resp.rows if r.step.id == tid)
        self.assertEqual(row.pr, "https://example.com/pr/3")

    def test_workflow_less_service_step_classifies_from_role_without_a_default(self):
        s = FakeStore()
        tid = s.create_step("review-findings: x", step="review-findings", role="human")
        resp = InboxUseCase(s, FlowService(FakeFs({}), s)).execute(InboxInput())
        row = next(r for r in resp.rows if r.step.id == tid)
        self.assertEqual(row.kind, "action")
        self.assertIsNone(row.pr)

    def test_row_pr_prefers_current_phase_over_earlier_phase(self):
        s = FakeStore()
        item = s.create_item("an item", workflow="wf")
        s.add_artifact(item, "pr", "https://example.com/pr/spec", label="spec")
        s.add_artifact(item, "pr", "https://example.com/pr/code", label="code")
        tid = s.create_step("await merge", step="code-await-merge", role="human", parent=item)
        flow = FlowService(FakeFs({"some-role": {"step": "code-await-merge", "phase": "code"}}), s)
        resp = InboxUseCase(s, flow).execute(InboxInput())
        row = next(r for r in resp.rows if r.step.id == tid)
        self.assertEqual(row.pr, "https://example.com/pr/code")

    def test_row_pr_prefers_spec_phase_at_a_spec_await_merge_step(self):
        s = FakeStore()
        item = s.create_item("an item", workflow="wf")
        s.add_artifact(item, "pr", "https://example.com/pr/code", label="code")
        s.add_artifact(item, "pr", "https://example.com/pr/spec", label="spec")
        tid = s.create_step("await merge", step="spec-await-merge", role="human", parent=item)
        fs = FakeFs(
            metas={"await-merge": {"step": "spec-await-merge"}},
            workflow=(
                "workspace:\n"
                "  spec-await-merge  specs\n\n"
                "phase:\n"
                "  spec-await-merge  spec\n\n"
                "nodes:\n"
                "  spec-await-merge  await-merge\n"
            ),
        )
        flow = FlowService(fs, s)
        resp = InboxUseCase(s, flow).execute(InboxInput())
        row = next(r for r in resp.rows if r.step.id == tid)
        self.assertEqual(row.pr, "https://example.com/pr/spec")

    def test_watched_step_excluded_while_its_feedback_step_is_open(self):
        s = FakeStore()
        _, watched = self._item_with_step(s, step_name="await-merge")
        item = s.get_node(watched).parent
        fb = s.create_step("handle feedback", step="handle-feedback", role="handle-feedback",
                            parent=item)
        s.add_artifact(fb, "watched-step", watched)
        resp = InboxUseCase(s, _flow_with_step(s, "await-merge")).execute(InboxInput())
        self.assertNotIn(watched, [r.step.id for r in resp.rows])

    def test_watched_step_returns_once_its_feedback_step_closes(self):
        s = FakeStore()
        _, watched = self._item_with_step(s, step_name="await-merge")
        item = s.get_node(watched).parent
        fb = s.create_step("handle feedback", step="handle-feedback", role="handle-feedback",
                            parent=item)
        s.add_artifact(fb, "watched-step", watched)
        s.close(fb, "done")
        resp = InboxUseCase(s, _flow_with_step(s, "await-merge")).execute(InboxInput())
        self.assertIn(watched, [r.step.id for r in resp.rows])


class TestShortProjectLabel(unittest.TestCase):
    def test_shortens_a_slash_qualified_value(self):
        self.assertEqual(short_project_label("kenmclennan/lightcycle"), "lightcycle")

    def test_leaves_a_bare_value_unchanged(self):
        self.assertEqual(short_project_label("lightcycle"), "lightcycle")

    def test_empty_for_none(self):
        self.assertEqual(short_project_label(None), "")

    def test_empty_for_empty_string(self):
        self.assertEqual(short_project_label(""), "")


if __name__ == "__main__":
    unittest.main()
