import datetime
import unittest

from the_grid.application.inspect import ActiveTasks, Queue, ShowTask, Status, Worklog
from tests.fake_store import FakeStore


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
        self.assertEqual([t["id"] for t in buckets["queue"]], [ready])
        self.assertEqual([t["id"] for t in buckets["mine"]], [human])
        self.assertEqual([t["id"] for t in buckets["active"]], [running])


class TestActiveTasks(unittest.TestCase):
    def test_returns_only_in_progress(self):
        s = FakeStore()
        s.create_task("waiting", step="build", role="coder")
        running = s.create_task("running", step="build", role="coder")
        s.assign(running, "worker-1")
        active = ActiveTasks(s).execute()
        self.assertEqual([t["id"] for t in active], [running])


class TestQueue(unittest.TestCase):
    def test_lists_ready_capped_at_n(self):
        s = FakeStore()
        ids = [s.create_task("t%d" % i, step="build", role="coder") for i in range(3)]
        out = Queue(s).execute(2)
        self.assertEqual(len(out), 2)
        self.assertTrue(set(t["id"] for t in out).issubset(set(ids)))

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


if __name__ == "__main__":
    unittest.main()
