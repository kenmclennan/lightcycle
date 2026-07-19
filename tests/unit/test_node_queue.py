import unittest

from tests.support.fake_fs import flow_from_metas
from lightcycle.domain.work import Node, NodeQueue, State

FLOW = flow_from_metas(
    {
        "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
        "ready-merge": {"step": "ready-merge", "routes": {"merged": "cleanup", "changes": "build"}},
    }
)


def fixed(flow):
    return lambda t: flow


def tk(id="t", **kw):
    return Node(id=id, **kw)


class TestClassifyForHuman(unittest.TestCase):
    def test_todo_when_no_step(self):
        self.assertEqual(tk(step=None).classify_for_human(FLOW), ("todo", []))

    def test_action_for_a_human_step(self):
        self.assertEqual(
            tk(step="ready-merge").classify_for_human(FLOW), ("action", ["changes", "merged"])
        )

    def test_blocked_for_an_agent_step_the_flow_does_know_still_blocked(self):
        self.assertEqual(
            tk(step="build").classify_for_human(FLOW), ("blocked", ["done", "unblock"])
        )

    def test_action_for_a_step_the_flow_does_not_know(self):
        self.assertEqual(
            tk(step="review-findings").classify_for_human(FLOW), ("action", [])
        )


class TestByLaneAndByState(unittest.TestCase):
    def test_by_lane_groups_states_into_lanes(self):
        q = NodeQueue(
            [
                tk(id="d", state=State.DONE),
                tk(id="a", state=State.IN_PROGRESS),
                tk(id="h", state=State.READY, role="human"),
                tk(id="r", state=State.READY, role="coder"),
                tk(id="b", state=State.BACKLOGGED, role="coder"),
            ]
        )
        lanes = q.by_lane()
        self.assertEqual([t.id for t in lanes["done"]], ["d"])
        self.assertEqual([t.id for t in lanes["active"]], ["a"])
        self.assertEqual([t.id for t in lanes["inbox"]], ["h"])
        self.assertEqual([t.id for t in lanes["queue"]], ["r"])
        self.assertEqual([t.id for t in lanes["blocked"]], ["b"])

    def test_by_state(self):
        q = NodeQueue([tk(state=State.READY), tk(state=State.DONE)])
        self.assertEqual(len(q.by_state(State.READY)), 1)


class TestForHuman(unittest.TestCase):
    def _queue(self, steps=None):
        steps = steps or [
            tk(id="a-1", state=State.READY, role="human", step=None),
            tk(id="a-2", state=State.READY, role="human", step="ready-merge"),
            tk(id="a-3", state=State.READY, role="human", step="build"),
        ]
        return NodeQueue(steps)

    def test_only_ready_human_tasks_are_considered(self):
        q = NodeQueue(
            [
                tk(id="r", state=State.READY, role="coder", step=None),
                tk(id="h", state=State.READY, role="human", step=None),
            ]
        )
        rows = q.for_human(fixed(FLOW), {"todo"})
        self.assertEqual([t.id for _, t in rows], ["h"])

    def test_inbox_returns_action_and_blocked(self):
        kinds = [c[0] for c, _ in self._queue().for_human(fixed(FLOW), {"action", "blocked"})]
        self.assertIn("action", kinds)
        self.assertIn("blocked", kinds)
        self.assertNotIn("todo", kinds)

    def test_backlog_returns_todo_only(self):
        kinds = [c[0] for c, _ in self._queue().for_human(fixed(FLOW), {"todo"})]
        self.assertEqual(kinds, ["todo"])

    def test_sorted_by_id(self):
        q = self._queue(
            [
                tk(id="b-3", state=State.READY, role="human", step=None),
                tk(id="b-1", state=State.READY, role="human", step=None),
                tk(id="b-2", state=State.READY, role="human", step=None),
            ]
        )
        self.assertEqual([t.id for _, t in q.for_human(fixed(FLOW), {"todo"})], ["b-1", "b-2", "b-3"])

    def test_limit_n(self):
        q = self._queue(
            [tk(id="c-%d" % i, state=State.READY, role="human", step=None) for i in range(5)]
        )
        self.assertEqual(len(q.for_human(fixed(FLOW), {"todo"}, n=2)), 2)

    def test_no_limit_returns_all(self):
        rows = self._queue().for_human(fixed(FLOW), {"action", "blocked", "todo"})
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
