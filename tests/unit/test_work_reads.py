import unittest

from the_grid.application.work import (ActiveTasksUseCase, BacklogInput, BacklogUseCase,
                                       InboxInput, InboxUseCase, MineUseCase, QueueInput,
                                       QueueUseCase, StatusUseCase)
from the_grid.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def _empty_flow(store):
    return FlowService(FakeFs({}), store)


class TestStatus(unittest.TestCase):
    def test_buckets_tasks_by_status(self):
        s = FakeStore()
        ready = s.create_task("ready one", step="build", role="coder")
        human = s.create_task("needs me", role="human")
        running = s.create_task("running", step="build", role="coder")
        s.assign(running, "worker-1")
        buckets = StatusUseCase(s).execute().buckets
        self.assertEqual([t.id for t in buckets["queue"]], [ready])
        self.assertEqual([t.id for t in buckets["mine"]], [human])
        self.assertEqual([t.id for t in buckets["active"]], [running])


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


class TestInboxBacklogMine(unittest.TestCase):
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

    def test_mine_combines_both_blocked_before_todo(self):
        s = self._store()
        rows = MineUseCase(s, _empty_flow(s)).execute().rows
        kinds = [row.kind for row in rows]
        self.assertEqual({row.task.id for row in rows}, {self.todo, self.gate})
        self.assertLess(kinds.index("blocked"), kinds.index("todo"))


if __name__ == "__main__":
    unittest.main()
