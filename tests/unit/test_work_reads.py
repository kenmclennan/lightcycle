import unittest

from the_grid.application.work import (ActiveTasksUseCase, BacklogInput, BacklogUseCase,
                                       InboxInput, InboxUseCase, QueueInput,
                                       QueueUseCase, ShowTaskInput, ShowTaskUseCase, StatusUseCase,
                                       TraceInput, TraceUseCase)
from the_grid.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def _empty_flow(store):
    return FlowService(FakeFs({}), store)


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
        sid = s.create_story("st")
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
        self.todo = s.create_task("todo item", role="human")          # no step -> backlog
        self.gate = s.create_task("a gate", step="review", role="human")  # stepped -> inbox
        return s

    def test_inbox_has_stepped_human_tasks_not_todos(self):
        s = self._store()
        ids = [row.task.id for row in InboxUseCase(s, _empty_flow(s)).execute(InboxInput()).rows]
        self.assertIn(self.gate, ids)
        self.assertNotIn(self.todo, ids)

    def test_backlog_has_todos_not_stepped(self):
        s = self._store()
        ids = [row.task.id for row in BacklogUseCase(s, _empty_flow(s)).execute(BacklogInput()).rows]
        self.assertIn(self.todo, ids)
        self.assertNotIn(self.gate, ids)

if __name__ == "__main__":
    unittest.main()
