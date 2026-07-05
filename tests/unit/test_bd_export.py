import unittest

from the_grid.adapters.bd_export import parse_bd_export_record


class TestParseBdExportRecord(unittest.TestCase):
    def test_parses_top_level_task(self):
        record = {
            "id": "the-grid-abc",
            "issue_type": "task",
            "title": "do the thing",
            "status": "open",
            "labels": ["for:coder", "step:build", "project:proj", "goal:goal1", "attention"],
            "notes": "some notes",
            "created_at": "2026-01-01T00:00:00Z",
            "metadata": {"artifacts": [{"type": "spec", "value": "/x.md"}]},
        }
        t = parse_bd_export_record(record)
        self.assertEqual(t.id, "the-grid-abc")
        self.assertEqual(t.type, "task")
        self.assertEqual(t.title, "do the thing")
        self.assertEqual(t.status, "open")
        self.assertEqual(t.role, "coder")
        self.assertEqual(t.step, "build")
        self.assertEqual(t.project, "proj")
        self.assertEqual(t.goal, "goal1")
        self.assertTrue(t.attention)
        self.assertEqual(t.notes, "some notes")
        self.assertEqual(t.created_at, "2026-01-01T00:00:00Z")
        self.assertEqual(len(t.artifacts), 1)
        self.assertEqual(t.artifacts[0].value, "/x.md")

    def test_parent_from_parent_child_dependency(self):
        record = {
            "id": "the-grid-abc.1",
            "issue_type": "task",
            "title": "child",
            "status": "open",
            "dependencies": [
                {"issue_id": "the-grid-abc.1", "depends_on_id": "the-grid-abc", "type": "parent-child"},
            ],
        }
        t = parse_bd_export_record(record)
        self.assertEqual(t.parent, "the-grid-abc")
        self.assertEqual(t.blocked_by, [])

    def test_blocked_by_from_blocks_dependency(self):
        record = {
            "id": "the-grid-abc.2",
            "issue_type": "task",
            "title": "blocked",
            "status": "open",
            "dependencies": [
                {"issue_id": "the-grid-abc.2", "depends_on_id": "the-grid-abc", "type": "parent-child"},
                {"issue_id": "the-grid-abc.2", "depends_on_id": "the-grid-abc.1", "type": "blocks"},
            ],
        }
        t = parse_bd_export_record(record)
        self.assertEqual(t.parent, "the-grid-abc")
        self.assertEqual(t.blocked_by, ["the-grid-abc.1"])

    def test_closed_task_preserves_close_reason_and_closed_at(self):
        record = {
            "id": "the-grid-xyz",
            "issue_type": "task",
            "title": "done thing",
            "status": "closed",
            "close_reason": "approved",
            "closed_at": "2026-02-02T00:00:00Z",
        }
        t = parse_bd_export_record(record)
        self.assertEqual(t.status, "closed")
        self.assertEqual(t.outcome, "approved")
        self.assertEqual(t.closed_at, "2026-02-02T00:00:00Z")

    def test_in_progress_task_preserves_assignee(self):
        record = {
            "id": "the-grid-clm",
            "issue_type": "task",
            "title": "claimed task",
            "status": "in_progress",
            "assignee": "coder-1",
        }
        t = parse_bd_export_record(record)
        self.assertEqual(t.status, "in_progress")
        self.assertEqual(t.assignee, "coder-1")

    def test_other_labels_preserved_without_structured_ones(self):
        record = {
            "id": "the-grid-lbl",
            "issue_type": "story",
            "title": "epic",
            "status": "closed",
            "labels": ["for:human", "retro-origin", "since:2026-01-01"],
        }
        t = parse_bd_export_record(record)
        self.assertEqual(t.role, "human")
        self.assertEqual(sorted(t.labels), ["retro-origin", "since:2026-01-01"])


if __name__ == "__main__":
    unittest.main()
