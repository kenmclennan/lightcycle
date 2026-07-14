import sqlite3
import unittest

from tests.support.sqlite_store_factory import make_sqlite_store
from tests.support.store_contract import StoreContractBase
from lightcycle.adapters import sqlite_store
from lightcycle.adapters.sqlite_store import SqliteStore


class TestSqliteStoreContract(StoreContractBase, unittest.TestCase):
    def make_store(self, now=None):
        return make_sqlite_store(now=now)


class TestSqliteStoreDisconnect(unittest.TestCase):
    def test_disconnect_closes_the_underlying_connection(self):
        s = make_sqlite_store()
        s.disconnect()
        with self.assertRaises(sqlite3.ProgrammingError):
            s.create_step("t")


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
        ):
            self.assertFalse(hasattr(SqliteStore, name), name)

    def test_removed_rename_maps_are_gone(self):
        self.assertFalse(hasattr(sqlite_store, "_ACTION_STEP_RENAMES"))
        self.assertFalse(hasattr(sqlite_store, "_ACTION_ROLE_RENAMES"))


if __name__ == "__main__":
    unittest.main()
