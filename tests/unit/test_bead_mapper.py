import unittest

from the_grid.adapters.bead import bead_to_task
from the_grid.domain.work import Status


def _bead(**over):
    b = {
        "id": "t-1",
        "title": "build it",
        "issue_type": "task",
        "labels": ["for:coder", "step:build", "project:grid", "goal:ship"],
        "metadata": {"artifacts": [{"type": "spec", "value": "s.md"}], "needs": "a branch"},
        "dependency_count": 2,
        "notes": "hi",
    }
    b.update(over)
    return b


class TestBeadToTask(unittest.TestCase):
    def test_typed_attribute_access(self):
        t = bead_to_task(_bead())
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
        st = bead_to_task(_bead()).status
        self.assertIsInstance(st, Status)
        self.assertEqual(st, Status.READY)
        self.assertEqual(st, "ready")

    def test_status_mapping(self):
        self.assertEqual(bead_to_task(_bead(status="closed")).status, "done")
        self.assertEqual(bead_to_task(_bead(assignee="w1")).status, "in-progress")
        self.assertEqual(bead_to_task(_bead(status="in_progress")).status, "in-progress")
        self.assertEqual(bead_to_task(_bead(labels=["for:human"])).status, "needs-human")
        self.assertEqual(bead_to_task(_bead()).status, "ready")

    def test_model_from_metadata(self):
        t = bead_to_task(_bead(metadata={"model": "sonnet"}))
        self.assertEqual(t.model, "sonnet")

    def test_model_absent_is_none(self):
        self.assertIsNone(bead_to_task(_bead()).model)

    def test_as_dict_is_a_plain_field_dict(self):
        d = bead_to_task(_bead()).as_dict()
        self.assertEqual(type(d), dict)
        self.assertEqual(d["id"], "t-1")
        self.assertEqual(d["step"], "build")
        self.assertEqual(d["status"], "ready")
        self.assertNotIn("workspace", d)


if __name__ == "__main__":
    unittest.main()
