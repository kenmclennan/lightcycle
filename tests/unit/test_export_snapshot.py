import json
import unittest

from tests.support.sqlite_store_factory import make_sqlite_store
from lightcycle.application.setup import ExportSnapshotUseCase


class TestExportSnapshot(unittest.TestCase):
    def test_export_reproduces_store_contents(self):
        store = make_sqlite_store()
        item = store.create_item("some work")
        store.add_artifact(item, "spec", "/specs/GRID-059.md")
        step = store.create_step("build it", step="build", role="agent", parent=item)
        store.note(step, "some notes")
        store.label_add(step, "retro-origin")
        blocker = store.create_step("blocker", parent=item)
        store.dep_add(step, blocker)
        store.close(blocker, "done")

        response = ExportSnapshotUseCase(store).execute()
        rows = {json.loads(line)["id"]: json.loads(line) for line in response.lines}

        self.assertEqual(set(rows), {item, step, blocker})

        story_row = rows[item]
        self.assertEqual(story_row["type"], "item")
        self.assertEqual(
            story_row["artifacts"],
            [{"type": "spec", "value": "/specs/GRID-059.md", "kind": "filepath"}],
        )

        task_row = rows[step]
        self.assertEqual(task_row["parent"], item)
        self.assertEqual(task_row["role"], "agent")
        self.assertEqual(task_row["step"], "build")
        self.assertEqual(task_row["notes"], "some notes")
        self.assertIn("retro-origin", task_row["labels"])
        self.assertEqual(task_row["blocked_by"], [blocker])

        blocker_row = rows[blocker]
        self.assertEqual(blocker_row["state"], "done")
        self.assertEqual(blocker_row["outcome"], "done")


if __name__ == "__main__":
    unittest.main()
