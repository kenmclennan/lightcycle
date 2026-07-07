import json
import unittest

from tests.support.sqlite_store_factory import make_sqlite_store
from lightcycle.application.setup import ExportSnapshotUseCase


class TestExportSnapshot(unittest.TestCase):
    def test_export_reproduces_store_contents(self):
        store = make_sqlite_store()
        epic = store.create_epic("epic")
        story = store.create_story("epic work", epic=epic)
        store.add_artifact(story, "spec", "/specs/GRID-059.md")
        task = store.create_task("build it", step="build", role="coder", parent=story)
        store.note(task, "some notes")
        store.label_add(task, "retro-origin")
        blocker = store.create_task("blocker", parent=story)
        store.dep_add(task, blocker)
        store.close(blocker, "done")

        response = ExportSnapshotUseCase(store).execute()
        rows = {json.loads(line)["id"]: json.loads(line) for line in response.lines}

        self.assertEqual(set(rows), {epic, story, task, blocker})

        story_row = rows[story]
        self.assertEqual(story_row["type"], "story")
        self.assertEqual(story_row["artifacts"], [{"type": "spec", "value": "/specs/GRID-059.md"}])

        task_row = rows[task]
        self.assertEqual(task_row["parent"], story)
        self.assertEqual(task_row["role"], "coder")
        self.assertEqual(task_row["step"], "build")
        self.assertEqual(task_row["notes"], "some notes")
        self.assertIn("retro-origin", task_row["labels"])
        self.assertEqual(task_row["blocked_by"], [blocker])

        blocker_row = rows[blocker]
        self.assertEqual(blocker_row["status"], "closed")
        self.assertEqual(blocker_row["close_reason"], "done")


if __name__ == "__main__":
    unittest.main()
