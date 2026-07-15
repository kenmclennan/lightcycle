import gzip
import os
import tempfile
import unittest

from lightcycle.adapters.backup import SqliteBackupAdapter
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.application.pool.backup import BackupUseCase
from tests.support.sqlite_store_factory import make_sqlite_store


class FakeConfig:
    def __init__(self, data_root, backups_dir, interval_minutes=20, retention=4):
        self._data_root = data_root
        self._backups_dir = backups_dir
        self._interval_minutes = interval_minutes
        self._retention = retention

    def data_root(self):
        return self._data_root

    def backups_dir(self):
        return self._backups_dir

    def backup_interval_minutes(self):
        return self._interval_minutes

    def backup_retention(self):
        return self._retention


def _adapter():
    store = make_sqlite_store()
    backups_dir = tempfile.mkdtemp()
    config = FakeConfig(store._config.data_root(), backups_dir)
    return SqliteBackupAdapter(config), store, backups_dir


class TestCreateSnapshot(unittest.TestCase):
    def test_restored_contents_match_the_source_at_snapshot_time(self):
        backup, store, backups_dir = _adapter()
        tid = store.create_step("t", role="coder")
        name = backup.create_snapshot(1000.0)
        self.assertTrue(os.path.exists(os.path.join(backups_dir, name)))
        store.close(tid, "done")
        store.disconnect()
        backup.restore(name)
        reopened = SqliteStore(store._config)
        self.assertEqual(reopened.get_node(tid).state, "ready")

    def test_snapshot_directory_created_if_absent(self):
        store = make_sqlite_store()
        backups_dir = os.path.join(tempfile.mkdtemp(), "nested", "backups")
        config = FakeConfig(store._config.data_root(), backups_dir)
        backup = SqliteBackupAdapter(config)
        name = backup.create_snapshot(1000.0)
        self.assertTrue(os.path.exists(os.path.join(backups_dir, name)))


class TestListSnapshots(unittest.TestCase):
    def test_orders_by_mtime_not_name(self):
        backup, store, backups_dir = _adapter()
        older_name = "store-20260101T000000Z.db.gz"
        newer_name = "store-20260102T000000Z.db.gz"
        for name in (older_name, newer_name):
            with gzip.open(os.path.join(backups_dir, name), "wb") as f:
                f.write(b"x")
        os.utime(os.path.join(backups_dir, older_name), (2000.0, 2000.0))
        os.utime(os.path.join(backups_dir, newer_name), (1000.0, 1000.0))
        snapshots = backup.list_snapshots()
        self.assertEqual(snapshots[0][0], older_name)

    def test_off_convention_file_is_excluded(self):
        backup, store, backups_dir = _adapter()
        real_name = backup.create_snapshot(1000.0)
        manual_name = "store-pre-LC88.3-note.db.gz"
        with gzip.open(os.path.join(backups_dir, manual_name), "wb") as f:
            f.write(b"x")
        os.utime(os.path.join(backups_dir, manual_name), (500.0, 500.0))
        snapshots = backup.list_snapshots()
        self.assertEqual([n for n, _ in snapshots], [real_name])


class TestPrune(unittest.TestCase):
    def test_keeps_newest_n_and_removes_the_rest(self):
        backup, store, backups_dir = _adapter()
        names = [backup.create_snapshot(1000.0 + i) for i in range(5)]
        removed = backup.prune(2)
        remaining = {n for n, _ in backup.list_snapshots()}
        self.assertEqual(len(remaining), 2)
        self.assertEqual(set(removed), set(names) - remaining)

    def test_never_removes_or_counts_a_manual_file(self):
        backup, store, backups_dir = _adapter()
        names = [backup.create_snapshot(1000.0 + i) for i in range(3)]
        manual_name = "store-pre-LC88.3-note.db.gz"
        with gzip.open(os.path.join(backups_dir, manual_name), "wb") as f:
            f.write(b"x")
        os.utime(os.path.join(backups_dir, manual_name), (1.0, 1.0))
        removed = backup.prune(2)
        remaining = {n for n, _ in backup.list_snapshots()}
        self.assertEqual(len(remaining), 2)
        self.assertEqual(set(removed), set(names) - remaining)
        self.assertTrue(os.path.exists(os.path.join(backups_dir, manual_name)))
        self.assertNotIn(manual_name, remaining)


class TestBackupUseCaseIntervalCheck(unittest.TestCase):
    def test_manual_file_does_not_poison_the_interval_check(self):
        backup, store, backups_dir = _adapter()
        real_name = backup.create_snapshot(1000.0)
        os.utime(os.path.join(backups_dir, real_name), (1000.0, 1000.0))
        manual_name = "store-zzz-manual.db.gz"
        with gzip.open(os.path.join(backups_dir, manual_name), "wb") as f:
            f.write(b"x")
        os.utime(os.path.join(backups_dir, manual_name), (1.0, 1.0))
        use_case = BackupUseCase(backup, backup._config)
        result = use_case.execute(1100.0)
        self.assertIsNone(result.created)


class TestRestore(unittest.TestCase):
    def test_restore_rejects_a_corrupt_snapshot_without_touching_the_live_file(self):
        backup, store, backups_dir = _adapter()
        bad_path = os.path.join(backups_dir, "store-bad.db.gz")
        with gzip.open(bad_path, "wb") as f:
            f.write(b"not a sqlite database")
        store_path = os.path.join(store._config.data_root(), "store.db")
        before = open(store_path, "rb").read()
        with self.assertRaises(ValueError):
            backup.restore("store-bad.db.gz")
        after = open(store_path, "rb").read()
        self.assertEqual(before, after)

    def test_restore_removes_stale_wal_and_shm_sidecars(self):
        backup, store, backups_dir = _adapter()
        name = backup.create_snapshot(1000.0)
        store_path = os.path.join(store._config.data_root(), "store.db")
        wal_path = store_path + "-wal"
        shm_path = store_path + "-shm"
        open(wal_path, "wb").close()
        open(shm_path, "wb").close()
        backup.restore(name)
        self.assertFalse(os.path.exists(wal_path))
        self.assertFalse(os.path.exists(shm_path))

    def test_restore_with_no_name_uses_the_newest_snapshot(self):
        backup, store, backups_dir = _adapter()
        backup.create_snapshot(1000.0)
        newest = backup.create_snapshot(2000.0)
        backup.restore(None)
        self.assertTrue(os.path.exists(os.path.join(backups_dir, newest)))


if __name__ == "__main__":
    unittest.main()
