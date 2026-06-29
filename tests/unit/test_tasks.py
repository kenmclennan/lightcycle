import unittest

from the_grid.core.tasks import (bucket, classify_mine, filter_by_status, label_value,
                             labels, partition_mine, task_from_bead)
from the_grid.domain.task import Task


def bead(**kw):
    base = {"id": "b-1", "title": "build: thing", "issue_type": "task"}
    base.update(kw)
    return base


def tk(**kw):
    kw.setdefault("id", "t")
    return Task(**kw)


class TestLabels(unittest.TestCase):
    def test_label_value_matches_prefix(self):
        b = bead(labels=["for:coder", "step:build", "project:x"])
        self.assertEqual(label_value(b, "for:"), "coder")
        self.assertEqual(label_value(b, "step:"), "build")
        self.assertIsNone(label_value(b, "goal:"))

    def test_labels_defaults_empty(self):
        self.assertEqual(labels(bead()), [])


class TestStatusMapping(unittest.TestCase):
    def test_ready(self):
        t = task_from_bead(bead(labels=["for:coder", "step:build"], status="open"))
        self.assertEqual(t.status, "ready")
        self.assertEqual(t.role, "coder")
        self.assertEqual(t.step, "build")

    def test_in_progress_via_assignee(self):
        t = task_from_bead(bead(labels=["for:coder"], status="open", assignee="S"))
        self.assertEqual(t.status, "in-progress")

    def test_in_progress_via_bd_status(self):
        t = task_from_bead(bead(labels=["for:coder"], status="in_progress"))
        self.assertEqual(t.status, "in-progress")

    def test_needs_human(self):
        t = task_from_bead(bead(labels=["for:human"], status="open"))
        self.assertEqual(t.status, "needs-human")

    def test_done(self):
        t = task_from_bead(bead(labels=["for:coder"], status="closed", close_reason="done"))
        self.assertEqual(t.status, "done")
        self.assertEqual(t.outcome, "done")

    def test_artifacts_from_metadata(self):
        t = task_from_bead(bead(metadata={"artifacts": [{"type": "spec", "value": "s.md"}]}))
        self.assertEqual(t.artifacts[0]["value"], "s.md")

    def test_notes_surfaced(self):
        t = task_from_bead(bead(notes="from review (rejected): fix #6"))
        self.assertEqual(t.notes, "from review (rejected): fix #6")

    def test_notes_absent_is_none(self):
        self.assertIsNone(task_from_bead(bead()).notes)


class TestBucketAndFilter(unittest.TestCase):
    def _tasks(self):
        return [
            tk(status="done"), tk(status="in-progress"), tk(status="needs-human"),
            tk(status="ready"), tk(status="blocked"),
        ]

    def test_bucket_partitions_by_status(self):
        b = bucket(self._tasks())
        self.assertEqual(len(b["done"]), 1)
        self.assertEqual(len(b["active"]), 1)
        self.assertEqual(len(b["mine"]), 1)
        self.assertEqual(len(b["queue"]), 1)
        self.assertEqual(len(b["blocked"]), 1)

    def test_filter_by_status(self):
        self.assertEqual(len(filter_by_status(self._tasks(), "ready")), 1)


class TestClassifyMine(unittest.TestCase):
    OWNER = {"build": "coder", "ready-merge": "human"}
    ROUTES = {"build": {"done": "review"}, "ready-merge": {"merged": "cleanup", "changes": "build"}}

    def test_todo_no_step(self):
        self.assertEqual(classify_mine(tk(step=None), self.OWNER, self.ROUTES), ("todo", []))

    def test_action_is_a_human_step(self):
        self.assertEqual(classify_mine(tk(step="ready-merge"), self.OWNER, self.ROUTES),
                         ("action", ["changes", "merged"]))

    def test_blocked_is_an_agent_step_plus_unblock(self):
        self.assertEqual(classify_mine(tk(step="build"), self.OWNER, self.ROUTES),
                         ("blocked", ["done", "unblock"]))


class TestPartitionMine(unittest.TestCase):
    OWNER = {"build": "coder", "ready-merge": "human"}
    ROUTES = {"build": {"done": "review"}, "ready-merge": {"merged": "cleanup", "changes": "build"}}

    def _tasks(self):
        return [
            tk(id="a-1", step=None, artifacts=[]),
            tk(id="a-2", step="ready-merge", artifacts=[]),
            tk(id="a-3", step="build", artifacts=[]),
        ]

    def test_inbox_returns_action_and_blocked(self):
        rows = partition_mine(self._tasks(), self.OWNER, self.ROUTES, {"action", "blocked"})
        kinds = [cls[0] for cls, _ in rows]
        self.assertIn("action", kinds)
        self.assertIn("blocked", kinds)
        self.assertNotIn("todo", kinds)

    def test_backlog_returns_todo_only(self):
        rows = partition_mine(self._tasks(), self.OWNER, self.ROUTES, {"todo"})
        kinds = [cls[0] for cls, _ in rows]
        self.assertEqual(kinds, ["todo"])

    def test_sorted_by_id(self):
        tasks = [
            tk(id="b-3", step=None, artifacts=[]),
            tk(id="b-1", step=None, artifacts=[]),
            tk(id="b-2", step=None, artifacts=[]),
        ]
        rows = partition_mine(tasks, self.OWNER, self.ROUTES, {"todo"})
        ids = [t.id for _, t in rows]
        self.assertEqual(ids, ["b-1", "b-2", "b-3"])

    def test_limit_n(self):
        tasks = [tk(id="c-%d" % i, step=None, artifacts=[]) for i in range(5)]
        rows = partition_mine(tasks, self.OWNER, self.ROUTES, {"todo"}, n=2)
        self.assertEqual(len(rows), 2)

    def test_no_limit_returns_all(self):
        rows = partition_mine(self._tasks(), self.OWNER, self.ROUTES, {"action", "blocked", "todo"})
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
