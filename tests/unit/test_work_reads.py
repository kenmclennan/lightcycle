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
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def _empty_flow(store):
    return FlowService(FakeFs({}), store)


class _Workers:
    def __init__(self, workers=None):
        self._workers = workers or []

    def workers_state(self):
        return self._workers


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
        resp = TraceUseCase(s, workers).execute(TraceInput(item=sid))
        self.assertEqual(resp.item.id, sid)
        self.assertEqual(resp.artifacts[0].type, "spec")
        self.assertEqual(resp.steps[0].id, k)
        self.assertEqual(resp.steps[0].log, "/l/k.log")


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

    def test_dep_blocked_task_lands_in_blocked_not_queue(self):
        s = FakeStore()
        blocker = s.create_step("blocker", step="build", role="coder")
        blocked = s.create_step("blocked", step="build", role="coder", deps=[blocker])
        lanes = StatusUseCase(s).execute().lanes
        self.assertEqual([t.id for t in lanes["blocked"]], [blocked])
        self.assertNotIn(blocked, [t.id for t in lanes["queue"]])

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


if __name__ == "__main__":
    unittest.main()
