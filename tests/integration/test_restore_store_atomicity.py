import os
import tempfile
import unittest

from lightcycle.adapters.backup import SqliteBackupAdapter
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.application.setup.restore_store import RestoreInput, RestoreStoreUseCase
from lightcycle.config import Config
from lightcycle.ports.lock import LockAcquisition, RunLockPort


class FakeLock(RunLockPort):
    def acquire(self):
        return LockAcquisition(True, os.getpid())

    def release(self):
        pass

    def is_running(self):
        return False

    def holder_pid(self):
        return None


class TestRestoreStoreAtomicity(unittest.TestCase):
    def test_a_failed_restore_leaves_the_live_store_intact(self):
        root = tempfile.mkdtemp()
        cfg_path = os.path.join(root, "config")
        with open(cfg_path, "w") as f:
            f.write("shortcode: GRID\nbackups-dir: %s\n" % os.path.join(root, "backups"))
        config = Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})
        store = SqliteStore(config)
        backup = SqliteBackupAdapter(config)

        item = store.create_item("keep me", "a description")
        name = backup.create_snapshot(now=1234567890.0)

        snapshot_path = os.path.join(root, "backups", name)
        with open(snapshot_path, "wb") as f:
            f.write(b"not a valid gzip file")

        with self.assertRaises(Exception):
            RestoreStoreUseCase(FakeLock(), store, backup, config).execute(
                RestoreInput(snapshot=name, force=True)
            )

        reopened = SqliteStore(config)
        self.assertEqual(reopened.get_node(item).title, "keep me")


if __name__ == "__main__":
    unittest.main()
