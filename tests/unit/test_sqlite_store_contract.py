import unittest

from tests.support.sqlite_store_factory import make_sqlite_store
from tests.support.store_contract import StoreContractBase
from lightcycle.adapters import sqlite_store
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.ports.store import StoreError
from tests.support.step_factory import create_owned_step


class TestSqliteStoreContract(StoreContractBase, unittest.TestCase):
    def make_store(self, now=None):
        return make_sqlite_store(now=now)

    def make_store_with_context_artifact_types(self, types):
        return make_sqlite_store(extra_config={"context-artifact-types": " ".join(types)})


class TestSqliteStoreDisconnect(unittest.TestCase):
    def test_disconnect_closes_the_underlying_connection(self):
        s = make_sqlite_store()
        s.release()
        with self.assertRaises(StoreError):
            create_owned_step(s, "t")


class TestSqliteStoreRequiresParent(unittest.TestCase):
    def test_create_step_without_parent_raises(self):
        s = make_sqlite_store()
        with self.assertRaises(ValueError):
            s.create_step()


class TestRemovedMigrationsLeaveNoDanglingReferences(unittest.TestCase):
    def test_removed_migration_methods_are_gone(self):
        for name in (
            "_migrate_history_ts",
            "_migrate_history_state_column",
            "_migrate_nodes_workflow",
            "_migrate_collapse_state",
            "_migrate_action_rename",
            "_migrated_state",
            "_status_indexes",
            "_backup_before_collapse",
            "_backup_before_action_rename",
            "_migrate_close_reason_to_outcome",
            "_migrate_artifact_fields",
            "_migrate_resume_fields",
            "_migrate_detach_items_from_themes",
            "_migrate_collapse_step_roles",
            "_migrate_brief_artifacts_into_description",
            "_migrate_phase_artifacts_into_runs",
            "_migrate_split_nodes",
            "_fold_comment_ledger_into_runs",
            "_step_artifact_folds",
            "_orphan_owner",
            "_repo_artifact_of",
            "_STEP_FOLDED_ARTIFACTS",
            "_RUN_FOLDED_ARTIFACTS",
            "_FOLDED_ARTIFACTS",
        ):
            self.assertFalse(hasattr(SqliteStore, name), name)

    def test_removed_rename_maps_are_gone(self):
        self.assertFalse(hasattr(sqlite_store, "_ACTION_STEP_RENAMES"))
        self.assertFalse(hasattr(sqlite_store, "_ACTION_ROLE_RENAMES"))
        self.assertFalse(hasattr(sqlite_store, "_INTERNAL_ARTIFACT_TYPES"))


if __name__ == "__main__":
    unittest.main()
