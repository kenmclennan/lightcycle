import unittest

from the_grid.domain.work import Status, Task
from the_grid.domain.work.task import label_value


def _bead(**over):
    b = {"id": "t-1", "title": "build it", "issue_type": "task",
         "labels": ["for:coder", "step:build", "project:grid", "goal:ship"],
         "metadata": {"artifacts": [{"type": "spec", "value": "s.md"}], "needs": "a branch"},
         "dependency_count": 2, "notes": "hi"}
    b.update(over)
    return b


class TestLabelValue(unittest.TestCase):
    def test_matches_prefix(self):
        b = _bead()
        self.assertEqual(label_value(b, "for:"), "coder")
        self.assertIsNone(label_value(b, "missing:"))


class TestTaskFromBead(unittest.TestCase):
    def test_typed_attribute_access(self):
        t = Task.from_bead(_bead())
        self.assertEqual(t.id, "t-1")
        self.assertEqual(t.title, "build it")
        self.assertEqual(t.role, "coder")
        self.assertEqual(t.step, "build")
        self.assertEqual(t.status, "ready")
        self.assertEqual(t.project, "grid")
        self.assertEqual(t.goal, "ship")
        self.assertEqual(t.artifacts[0].type, "spec")
        self.assertEqual(t.needs, "a branch")
        self.assertEqual(t.deps, 2)

    def test_status_is_the_typed_value_object(self):
        st = Task.from_bead(_bead()).status
        self.assertIsInstance(st, Status)
        self.assertEqual(st, Status.READY)
        self.assertEqual(st, "ready")  # still string-equal for legacy comparisons

    def test_status_mapping(self):
        self.assertEqual(Task.from_bead(_bead(status="closed")).status, "done")
        self.assertEqual(Task.from_bead(_bead(assignee="w1")).status, "in-progress")
        self.assertEqual(Task.from_bead(_bead(status="in_progress")).status, "in-progress")
        self.assertEqual(Task.from_bead(_bead(labels=["for:human"])).status, "needs-human")
        self.assertEqual(Task.from_bead(_bead()).status, "ready")

    def test_as_dict_is_a_plain_field_dict(self):
        t = Task.from_bead(_bead())
        d = t.as_dict()
        self.assertEqual(type(d), dict)
        self.assertEqual(d["id"], "t-1")
        self.assertEqual(d["step"], "build")
        self.assertEqual(d["status"], "ready")
        self.assertNotIn("workspace", d)  # no enrichments


if __name__ == "__main__":
    unittest.main()
