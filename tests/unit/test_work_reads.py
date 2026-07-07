import datetime
import time
import unittest

from lightcycle.application.work import (
    ActiveTasksUseCase,
    BacklogInput,
    BacklogUseCase,
    InboxInput,
    InboxUseCase,
    QueueInput,
    QueueUseCase,
    ShowTaskInput,
    ShowTaskUseCase,
    StatusUseCase,
    TraceInput,
    TraceUseCase,
)
from lightcycle.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def _empty_flow(store):
    return FlowService(FakeFs({}), store)


def _settled_now():
    return time.time() + 7200


def _ts(date_str):
    d = datetime.date.fromisoformat(date_str)
    return float(datetime.datetime(d.year, d.month, d.day, 12, 0, 0).timestamp())


class _Workers:
    def __init__(self, workers=None):
        self._workers = workers or []

    def workers_state(self):
        return self._workers


class TestShowTask(unittest.TestCase):
    def test_returns_task_view(self):
        s = FakeStore()
        tid = s.create_task("build: x", step="build", role="coder")
        view = ShowTaskUseCase(s).execute(ShowTaskInput(task=tid)).view
        self.assertEqual(view.task.id, tid)
        self.assertEqual(view.task.title, "build: x")
        self.assertIn("story_artifacts", view.as_dict())


class TestTrace(unittest.TestCase):
    def test_assembles_story_artifacts_tasks_and_logs(self):
        s = FakeStore()
        sid = s.create_story("st", epic=s.create_epic("epic"))
        s.add_artifact(sid, "spec", "specs/x.md")
        k = s.create_task("build: x", step="build", role="coder", parent=sid)
        workers = _Workers([{"role": "coder", "task": k, "log": "/l/k.log"}])
        resp = TraceUseCase(s, workers).execute(TraceInput(story=sid))
        self.assertEqual(resp.story.id, sid)
        self.assertEqual(resp.artifacts[0].type, "spec")
        self.assertEqual(resp.tasks[0].id, k)
        self.assertEqual(resp.tasks[0].log, "/l/k.log")


class TestStatus(unittest.TestCase):
    def test_lanes_tasks_by_status(self):
        s = FakeStore()
        ready = s.create_task("ready one", step="build", role="coder")
        human = s.create_task("needs me", role="human")
        running = s.create_task("running", step="build", role="coder")
        s.assign(running, "worker-1")
        lanes = StatusUseCase(s).execute().lanes
        self.assertEqual([t.id for t in lanes["queue"]], [ready])
        self.assertEqual([t.id for t in lanes["inbox"]], [human])
        self.assertEqual([t.id for t in lanes["active"]], [running])

    def test_dep_blocked_task_lands_in_blocked_not_queue(self):
        s = FakeStore()
        blocker = s.create_task("blocker", step="build", role="coder")
        blocked = s.create_task("blocked", step="build", role="coder", deps=[blocker])
        lanes = StatusUseCase(s).execute().lanes
        self.assertEqual([t.id for t in lanes["blocked"]], [blocked])
        self.assertNotIn(blocked, [t.id for t in lanes["queue"]])


class TestActiveTasks(unittest.TestCase):
    def test_returns_only_in_progress(self):
        s = FakeStore()
        s.create_task("waiting", step="build", role="coder")
        running = s.create_task("running", step="build", role="coder")
        s.assign(running, "worker-1")
        self.assertEqual([t.id for t in ActiveTasksUseCase(s).execute().tasks], [running])


class TestQueue(unittest.TestCase):
    def test_lists_ready_capped_at_n(self):
        s = FakeStore()
        ids = [s.create_task("t%d" % i, step="build", role="coder") for i in range(3)]
        out = QueueUseCase(s).execute(QueueInput(n=2)).tasks
        self.assertEqual(len(out), 2)
        self.assertTrue(set(t.id for t in out).issubset(set(ids)))

    def test_default_n_is_ten(self):
        s = FakeStore()
        for i in range(12):
            s.create_task("t%d" % i, step="build", role="coder")
        self.assertEqual(len(QueueUseCase(s).execute(QueueInput()).tasks), 10)


class TestInboxBacklog(unittest.TestCase):
    def _store(self):
        s = FakeStore()
        self.todo = s.create_task("todo item", role="human")
        self.gate = s.create_task("a gate", step="review", role="human")
        return s

    def test_inbox_has_stepped_human_tasks_not_todos(self):
        s = self._store()
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        ids = [row.task.id for row in resp.rows]
        self.assertIn(self.gate, ids)
        self.assertNotIn(self.todo, ids)

    def test_backlog_has_todos_not_stepped(self):
        s = self._store()
        ids = [
            row.task.id for row in BacklogUseCase(s, _empty_flow(s)).execute(BacklogInput()).rows
        ]
        self.assertIn(self.todo, ids)
        self.assertNotIn(self.gate, ids)


class TestInboxCandidateEpics(unittest.TestCase):
    def test_all_closed_stories_epic_is_candidate(self):
        s = FakeStore()
        epic = s.create_epic("My Epic")
        s.close(s.create_story("story 1", epic=epic), "done")
        s.close(s.create_story("story 2", epic=epic), "done")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        self.assertIn(epic, [e.id for e in resp.candidate_epics])

    def test_one_open_story_epic_not_candidate(self):
        s = FakeStore()
        epic = s.create_epic("My Epic")
        s.close(s.create_story("story 1", epic=epic), "done")
        s.create_story("story 2", epic=epic)
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        self.assertNotIn(epic, [e.id for e in resp.candidate_epics])

    def test_no_children_epic_not_candidate(self):
        s = FakeStore()
        epic = s.create_epic("Empty Epic")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        self.assertNotIn(epic, [e.id for e in resp.candidate_epics])

    def test_closed_epic_not_candidate(self):
        s = FakeStore()
        epic = s.create_epic("Closed Epic")
        s.close(s.create_story("story", epic=epic), "done")
        s.close(epic, "done")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        self.assertNotIn(epic, [e.id for e in resp.candidate_epics])

    def test_candidate_epic_has_closed_story_count(self):
        s = FakeStore()
        epic = s.create_epic("My Epic")
        for i in range(3):
            s.close(s.create_story("story %d" % i, epic=epic), "done")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        candidates = {e.id: e for e in resp.candidate_epics}
        self.assertEqual(candidates[epic].closed_story_count, 3)

    def test_existing_inbox_rows_unchanged(self):
        s = FakeStore()
        epic = s.create_epic("My Epic")
        s.close(s.create_story("story", epic=epic), "done")
        gate = s.create_task("a gate", step="review", role="human")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        self.assertIn(gate, [row.task.id for row in resp.rows])


class TestInboxCandidateEpicQuiescence(unittest.TestCase):
    def _close_story(self, store, epic, title, closed_date_str):
        sid = store.create_story(title, epic=epic)
        store.close(sid, "done")
        store._records[sid]["closed_at"] = closed_date_str + "T12:00:00.000000"
        return sid

    def test_epic_not_candidate_until_recency_window_elapses(self):
        s = FakeStore()
        epic = s.create_epic("My Epic")
        self._close_story(s, epic, "story", "2026-07-04")

        just_closed = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_ts("2026-07-04")))
        self.assertNotIn(epic, [e.id for e in just_closed.candidate_epics])

        settled = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_ts("2026-07-06")))
        self.assertIn(epic, [e.id for e in settled.candidate_epics])

    def test_recency_gate_uses_latest_of_multiple_story_closures(self):
        s = FakeStore()
        epic = s.create_epic("My Epic")
        self._close_story(s, epic, "story 1", "2026-07-01")
        self._close_story(s, epic, "story 2", "2026-07-04")

        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_ts("2026-07-04")))
        self.assertNotIn(epic, [e.id for e in resp.candidate_epics])


class TestInboxAttentionFlag(unittest.TestCase):
    def test_flagged_task_appears_in_inbox_as_triage(self):
        s = FakeStore()
        tid = s.create_task("urgent finding", role="human", attention=True)
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        ids = [row.task.id for row in resp.rows]
        kinds = {row.task.id: row.kind for row in resp.rows}
        self.assertIn(tid, ids)
        self.assertEqual(kinds[tid], "triage")

    def test_unflagged_task_absent_from_inbox(self):
        s = FakeStore()
        tid = s.create_task("someday idea", role="human")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        self.assertNotIn(tid, [row.task.id for row in resp.rows])

    def test_closing_flagged_task_removes_it_from_inbox(self):
        s = FakeStore()
        tid = s.create_task("urgent finding", role="human", attention=True)
        s.close(tid, "done")
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        self.assertNotIn(tid, [row.task.id for row in resp.rows])

    def test_flagged_task_title_accessible_via_row(self):
        s = FakeStore()
        tid = s.create_task("audit: spec gaps", role="human", attention=True)
        resp = InboxUseCase(s, _empty_flow(s)).execute(InboxInput(now=_settled_now()))
        row = next(r for r in resp.rows if r.task.id == tid)
        self.assertEqual(row.task.title, "audit: spec gaps")


if __name__ == "__main__":
    unittest.main()
