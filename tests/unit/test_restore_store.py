import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.restore_store import RestoreInput, RestoreStoreUseCase
from lightcycle.ports.backup import BackupPort, Snapshot
from lightcycle.ports.lock import LockAcquisition, RunLockPort
from tests.support.fake_store import FakeStore


class FakeLock(RunLockPort):
    def __init__(self, acquire_result=LockAcquisition(True, 123), running=False):
        self._acquire_result = acquire_result
        self._running = running
        self.released = False

    def acquire(self):
        return self._acquire_result

    def release(self):
        self.released = True

    def is_running(self):
        return self._running

    def holder_pid(self):
        return 123 if self._running else None


class FakeBackup(BackupPort):
    def __init__(self, snapshots=None, restore_error=None):
        self._snapshots = list(snapshots or [])
        self._restore_error = restore_error
        self.restore_called_with = None

    def list_snapshots(self):
        return list(self._snapshots)

    def create_snapshot(self, now):
        raise NotImplementedError

    def prune(self, keep):
        raise NotImplementedError

    def restore(self, name):
        self.restore_called_with = name
        if self._restore_error is not None:
            raise self._restore_error


class FakeConfig:
    def __init__(self, backups_dir="/backups"):
        self._backups_dir = backups_dir

    def backups_dir(self):
        return self._backups_dir


class TestRestoreStoreUseCase(unittest.TestCase):
    def test_no_snapshots_raises_naming_the_backups_dir(self):
        store = FakeStore()
        with self.assertRaises(UseCaseError) as ctx:
            RestoreStoreUseCase(FakeLock(), store, FakeBackup(snapshots=[]), FakeConfig()).execute(
                RestoreInput(snapshot=None, force=True)
            )
        self.assertIn("/backups", str(ctx.exception))

    def test_named_snapshot_not_found_raises_naming_it(self):
        store = FakeStore()
        backup = FakeBackup(snapshots=[Snapshot("store-a.db.gz", 1.0)])
        with self.assertRaises(UseCaseError) as ctx:
            RestoreStoreUseCase(FakeLock(), store, backup, FakeConfig()).execute(
                RestoreInput(snapshot="ghost.db.gz", force=True)
            )
        self.assertIn("ghost.db.gz", str(ctx.exception))
        self.assertIsNone(backup.restore_called_with)

    def test_missing_force_raises_naming_the_target(self):
        store = FakeStore()
        backup = FakeBackup(snapshots=[Snapshot("store-a.db.gz", 1.0)])
        with self.assertRaises(UseCaseError) as ctx:
            RestoreStoreUseCase(FakeLock(), store, backup, FakeConfig()).execute(
                RestoreInput(snapshot=None, force=False)
            )
        self.assertIn("store-a.db.gz", str(ctx.exception))
        self.assertIsNone(backup.restore_called_with)

    def test_lock_held_raises_naming_the_holder_pid(self):
        store = FakeStore()
        backup = FakeBackup(snapshots=[Snapshot("store-a.db.gz", 1.0)])
        lock = FakeLock(acquire_result=LockAcquisition(False, 999))
        with self.assertRaises(UseCaseError) as ctx:
            RestoreStoreUseCase(lock, store, backup, FakeConfig()).execute(
                RestoreInput(snapshot=None, force=True)
            )
        self.assertIn("999", str(ctx.exception))
        self.assertIsNone(backup.restore_called_with)

    def test_happy_path_releases_the_store_before_restoring_and_releases_the_lock(self):
        store = FakeStore()
        calls = []
        store.release = lambda: calls.append("release")

        backup = FakeBackup(snapshots=[Snapshot("store-a.db.gz", 1234.0)])

        def _restore(name):
            calls.append("restore")
            backup.restore_called_with = name

        backup.restore = _restore
        lock = FakeLock()
        resp = RestoreStoreUseCase(lock, store, backup, FakeConfig()).execute(
            RestoreInput(snapshot=None, force=True)
        )
        self.assertEqual(calls, ["release", "restore"])
        self.assertTrue(lock.released)
        self.assertEqual(resp.snapshot, "store-a.db.gz")
        self.assertEqual(resp.taken_at, 1234.0)

    def test_backup_restore_error_propagates_and_the_lock_is_still_released(self):
        store = FakeStore()
        backup = FakeBackup(
            snapshots=[Snapshot("store-a.db.gz", 1.0)], restore_error=ValueError("bad snapshot")
        )
        lock = FakeLock()
        with self.assertRaises(ValueError):
            RestoreStoreUseCase(lock, store, backup, FakeConfig()).execute(
                RestoreInput(snapshot=None, force=True)
            )
        self.assertTrue(lock.released)

    def test_no_snapshot_given_selects_the_most_recent(self):
        store = FakeStore()
        backup = FakeBackup(
            snapshots=[Snapshot("store-newest.db.gz", 2.0), Snapshot("store-older.db.gz", 1.0)]
        )
        resp = RestoreStoreUseCase(FakeLock(), store, backup, FakeConfig()).execute(
            RestoreInput(snapshot=None, force=True)
        )
        self.assertEqual(resp.snapshot, "store-newest.db.gz")
        self.assertEqual(backup.restore_called_with, "store-newest.db.gz")


if __name__ == "__main__":
    unittest.main()
