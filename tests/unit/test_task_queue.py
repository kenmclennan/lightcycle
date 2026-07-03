import unittest

from the_grid.domain.flow import Flow
from the_grid.domain.work import Task, TaskQueue

FLOW = Flow.assemble(
    {
        "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
        "ready-merge": {"step": "ready-merge", "routes": {"merged": "cleanup", "changes": "build"}},
    }
)


def tk(id="t", **kw):
    return Task(id=id, **kw)


class TestClassifyForHuman(unittest.TestCase):
    def test_todo_when_no_step(self):
        self.assertEqual(tk(step=None).classify_for_human(FLOW), ("todo", []))

    def test_action_for_a_human_step(self):
        self.assertEqual(
            tk(step="ready-merge").classify_for_human(FLOW), ("action", ["changes", "merged"])
        )

    def test_blocked_for_an_agent_step_plus_unblock(self):
        self.assertEqual(
            tk(step="build").classify_for_human(FLOW), ("blocked", ["done", "unblock"])
        )


class TestByLaneAndByStatus(unittest.TestCase):
    def test_by_lane_groups_statuses_into_lanes(self):
        q = TaskQueue(
            [
                tk(id="d", status="done"),
                tk(id="a", status="in-progress"),
                tk(id="h", status="needs-human"),
                tk(id="r", status="ready"),
                tk(id="b", status="ready"),
            ]
        )
        lanes = q.by_lane(ready_ids={"r"})
        self.assertEqual([t.id for t in lanes["done"]], ["d"])
        self.assertEqual([t.id for t in lanes["active"]], ["a"])
        self.assertEqual([t.id for t in lanes["inbox"]], ["h"])
        self.assertEqual([t.id for t in lanes["queue"]], ["r"])
        self.assertEqual([t.id for t in lanes["blocked"]], ["b"])

    def test_by_status(self):
        q = TaskQueue([tk(status="ready"), tk(status="done")])
        self.assertEqual(len(q.by_status("ready")), 1)


class TestForHuman(unittest.TestCase):
    def _queue(self, tasks=None):
        tasks = tasks or [
            tk(id="a-1", status="needs-human", step=None),
            tk(id="a-2", status="needs-human", step="ready-merge"),
            tk(id="a-3", status="needs-human", step="build"),
        ]
        return TaskQueue(tasks)

    def test_only_needs_human_tasks_are_considered(self):
        q = TaskQueue(
            [tk(id="r", status="ready", step=None), tk(id="h", status="needs-human", step=None)]
        )
        rows = q.for_human(FLOW, {"todo"})
        self.assertEqual([t.id for _, t in rows], ["h"])

    def test_inbox_returns_action_and_blocked(self):
        kinds = [c[0] for c, _ in self._queue().for_human(FLOW, {"action", "blocked"})]
        self.assertIn("action", kinds)
        self.assertIn("blocked", kinds)
        self.assertNotIn("todo", kinds)

    def test_backlog_returns_todo_only(self):
        kinds = [c[0] for c, _ in self._queue().for_human(FLOW, {"todo"})]
        self.assertEqual(kinds, ["todo"])

    def test_sorted_by_id(self):
        q = self._queue(
            [
                tk(id="b-3", status="needs-human", step=None),
                tk(id="b-1", status="needs-human", step=None),
                tk(id="b-2", status="needs-human", step=None),
            ]
        )
        self.assertEqual([t.id for _, t in q.for_human(FLOW, {"todo"})], ["b-1", "b-2", "b-3"])

    def test_limit_n(self):
        q = self._queue([tk(id="c-%d" % i, status="needs-human", step=None) for i in range(5)])
        self.assertEqual(len(q.for_human(FLOW, {"todo"}, n=2)), 2)

    def test_no_limit_returns_all(self):
        rows = self._queue().for_human(FLOW, {"action", "blocked", "todo"})
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
