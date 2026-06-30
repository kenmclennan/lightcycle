import datetime
import unittest

from the_grid.application.inspect import (ActiveTasks, Backlog, FlowCheck, Inbox, Mine,
                                          Queue, ShowTask, Status, Worklog)
from the_grid.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def _empty_flow(store):
    return FlowService(FakeFs({}), store)


class TestShowTask(unittest.TestCase):
    def test_returns_task_view(self):
        s = FakeStore()
        tid = s.create_task("build: x", step="build", role="coder")
        view = ShowTask(s).execute(tid)
        self.assertEqual(view["id"], tid)
        self.assertEqual(view["title"], "build: x")
        self.assertIn("story_artifacts", view)


class TestStatus(unittest.TestCase):
    def test_buckets_tasks_by_status(self):
        s = FakeStore()
        ready = s.create_task("ready one", step="build", role="coder")
        human = s.create_task("needs me", role="human")
        running = s.create_task("running", step="build", role="coder")
        s.assign(running, "worker-1")
        buckets = Status(s).execute()
        self.assertEqual([t.id for t in buckets["queue"]], [ready])
        self.assertEqual([t.id for t in buckets["mine"]], [human])
        self.assertEqual([t.id for t in buckets["active"]], [running])


class TestActiveTasks(unittest.TestCase):
    def test_returns_only_in_progress(self):
        s = FakeStore()
        s.create_task("waiting", step="build", role="coder")
        running = s.create_task("running", step="build", role="coder")
        s.assign(running, "worker-1")
        active = ActiveTasks(s).execute()
        self.assertEqual([t.id for t in active], [running])


class TestQueue(unittest.TestCase):
    def test_lists_ready_capped_at_n(self):
        s = FakeStore()
        ids = [s.create_task("t%d" % i, step="build", role="coder") for i in range(3)]
        out = Queue(s).execute(2)
        self.assertEqual(len(out), 2)
        self.assertTrue(set(t.id for t in out).issubset(set(ids)))

    def test_default_n_is_ten(self):
        s = FakeStore()
        for i in range(12):
            s.create_task("t%d" % i, step="build", role="coder")
        self.assertEqual(len(Queue(s).execute()), 10)


class TestWorklog(unittest.TestCase):
    def test_lists_stories_closed_in_period(self):
        s = FakeStore()
        sid = s.create_story("shipped story")
        s.close(sid, "merged")
        today = datetime.date.today()
        entries = Worklog(s).execute([], today)
        self.assertIn(sid, [e["id"] for e in entries])

    def test_empty_when_nothing_closed(self):
        s = FakeStore()
        s.create_story("still open")
        self.assertEqual(Worklog(s).execute([], datetime.date.today()), [])


class TestInboxBacklogMine(unittest.TestCase):
    def _store(self):
        s = FakeStore()
        self.todo = s.create_task("todo item", role="human")          # no step -> backlog
        self.gate = s.create_task("a gate", step="review", role="human")  # stepped -> inbox
        return s

    def test_inbox_has_stepped_human_tasks_not_todos(self):
        s = self._store()
        ids = [t.id for _cls, t in Inbox(s, _empty_flow(s)).execute()]
        self.assertIn(self.gate, ids)
        self.assertNotIn(self.todo, ids)

    def test_backlog_has_todos_not_stepped(self):
        s = self._store()
        ids = [t.id for _cls, t in Backlog(s, _empty_flow(s)).execute()]
        self.assertIn(self.todo, ids)
        self.assertNotIn(self.gate, ids)

    def test_mine_combines_both_blocked_before_todo(self):
        s = self._store()
        rows = Mine(s, _empty_flow(s)).execute()
        kinds = [cls[0] for cls, _t in rows]
        self.assertEqual(set(t.id for _c, t in rows), {self.todo, self.gate})
        self.assertLess(kinds.index("blocked"), kinds.index("todo"))


class TestFlowCheck(unittest.TestCase):
    def test_returns_owner_routes_and_analysis(self):
        metas = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
        result = FlowCheck(FlowService(FakeFs(metas), FakeStore())).execute()
        self.assertEqual(result["owner"]["build"], "coder")
        self.assertEqual(result["routes"]["build"], {"done": "review"})
        self.assertIn("ok", result["analysis"])


if __name__ == "__main__":
    unittest.main()
