import json
import unittest

from tests.support.sqlite_store_factory import make_sqlite_store
from the_grid.adapters.bd_export import parse_bd_export_lines
from the_grid.application.errors import UseCaseError
from the_grid.application.setup import (
    MigrateFromBdExportInput,
    MigrateFromBdExportUseCase,
)
from the_grid.domain.work import Status

_EXPORT_RECORDS = [
    {
        "id": "the-grid-8fm",
        "issue_type": "story",
        "title": "sqlite migration",
        "status": "open",
        "created_at": "2026-06-01T00:00:00Z",
        "metadata": {"artifacts": [{"type": "spec", "value": "/specs/GRID-059.md"}]},
    },
    {
        "id": "the-grid-8fm.1",
        "issue_type": "task",
        "title": "build: migration",
        "status": "closed",
        "close_reason": "approved",
        "closed_at": "2026-06-02T00:00:00Z",
        "created_at": "2026-06-01T01:00:00Z",
        "notes": "went well",
        "labels": ["for:coder", "step:build", "attention"],
        "dependencies": [
            {"issue_id": "the-grid-8fm.1", "depends_on_id": "the-grid-8fm", "type": "parent-child"},
        ],
    },
    {
        "id": "the-grid-8fm.2",
        "issue_type": "task",
        "title": "review: migration",
        "status": "open",
        "created_at": "2026-06-01T02:00:00Z",
        "labels": ["for:human", "step:review", "retro-origin"],
        "dependencies": [
            {"issue_id": "the-grid-8fm.2", "depends_on_id": "the-grid-8fm", "type": "parent-child"},
            {"issue_id": "the-grid-8fm.2", "depends_on_id": "the-grid-8fm.1", "type": "blocks"},
        ],
    },
]


def _parsed_tasks(records=_EXPORT_RECORDS):
    return parse_bd_export_lines(json.dumps(r) for r in records)


class TestMigrateFromBdExport(unittest.TestCase):
    def test_round_trip_preserves_ids_hierarchy_and_fields(self):
        store = make_sqlite_store()
        use_case = MigrateFromBdExportUseCase(store)

        response = use_case.execute(MigrateFromBdExportInput(tasks=_parsed_tasks()))

        self.assertEqual(response.migrated_count, 3)

        story = store.get_task("the-grid-8fm")
        self.assertEqual(story.type, "story")
        self.assertEqual(story.title, "sqlite migration")
        artifacts = store.story_artifacts("the-grid-8fm")
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].value, "/specs/GRID-059.md")

        built = store.get_task("the-grid-8fm.1")
        self.assertEqual(built.parent, "the-grid-8fm")
        self.assertEqual(built.role, "coder")
        self.assertEqual(built.step, "build")
        self.assertTrue(built.attention)
        self.assertEqual(built.notes, "went well")
        self.assertEqual(built.outcome, "approved")
        self.assertEqual(built.closed_at, "2026-06-02T00:00:00Z")

        reviewed = store.get_task("the-grid-8fm.2")
        self.assertEqual(reviewed.parent, "the-grid-8fm")
        self.assertEqual(reviewed.role, "human")
        self.assertEqual(reviewed.deps, 0)

        children = {t.id for t in store.children("the-grid-8fm")}
        self.assertEqual(children, {"the-grid-8fm.1", "the-grid-8fm.2"})

    def test_blocked_dependency_counted_until_blocker_closes(self):
        store = make_sqlite_store()
        use_case = MigrateFromBdExportUseCase(store)
        open_records = [dict(r) for r in _EXPORT_RECORDS]
        open_records[1]["status"] = "open"
        open_records[1].pop("close_reason", None)
        open_records[1].pop("closed_at", None)

        use_case.execute(MigrateFromBdExportInput(tasks=_parsed_tasks(open_records)))

        reviewed = store.get_task("the-grid-8fm.2")
        self.assertEqual(reviewed.deps, 1)

    def test_new_child_id_does_not_collide_with_migrated_sibling(self):
        store = make_sqlite_store()
        use_case = MigrateFromBdExportUseCase(store)
        use_case.execute(MigrateFromBdExportInput(tasks=_parsed_tasks()))

        new_child = store.create_task("follow-up", parent="the-grid-8fm")

        self.assertEqual(new_child, "the-grid-8fm.3")

    def test_claimed_task_preserves_assignee_and_in_progress_status(self):
        store = make_sqlite_store()
        use_case = MigrateFromBdExportUseCase(store)
        records = [dict(r) for r in _EXPORT_RECORDS]
        records.append({
            "id": "the-grid-8fm.3",
            "issue_type": "task",
            "title": "claimed work",
            "status": "in_progress",
            "assignee": "coder-1",
            "dependencies": [
                {"issue_id": "the-grid-8fm.3", "depends_on_id": "the-grid-8fm", "type": "parent-child"},
            ],
        })

        use_case.execute(MigrateFromBdExportInput(tasks=_parsed_tasks(records)))

        claimed = store.get_task("the-grid-8fm.3")
        self.assertEqual(claimed.claimed_by, "coder-1")
        self.assertEqual(claimed.status, Status.IN_PROGRESS)

    def test_refuses_non_empty_target_without_force(self):
        store = make_sqlite_store()
        store.create_task("existing")
        use_case = MigrateFromBdExportUseCase(store)

        with self.assertRaises(UseCaseError):
            use_case.execute(MigrateFromBdExportInput(tasks=_parsed_tasks()))

    def test_force_migrates_into_non_empty_target(self):
        store = make_sqlite_store()
        store.create_task("existing")
        use_case = MigrateFromBdExportUseCase(store)

        response = use_case.execute(
            MigrateFromBdExportInput(tasks=_parsed_tasks(), force=True)
        )

        self.assertEqual(response.migrated_count, 3)
        self.assertIsNotNone(store.get_task("the-grid-8fm"))


if __name__ == "__main__":
    unittest.main()
