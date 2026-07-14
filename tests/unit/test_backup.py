import unittest

from lightcycle.application.pool.backup import BackupUseCase


class FakeBackupPort:
    def __init__(self, snapshots=None):
        self._snapshots = snapshots or []
        self.created = []
        self.pruned_with = None

    def list_snapshots(self):
        return list(self._snapshots)

    def create_snapshot(self, now):
        name = "store-%d.db.gz" % now
        self._snapshots.insert(0, (name, now))
        self.created.append(name)
        return name

    def prune(self, keep):
        self.pruned_with = keep
        removed = [n for n, _ in self._snapshots[keep:]]
        self._snapshots = self._snapshots[:keep]
        return removed


class FakeConfig:
    def __init__(self, interval_minutes=15, retention=96):
        self._interval_minutes = interval_minutes
        self._retention = retention

    def backup_interval_minutes(self):
        return self._interval_minutes

    def backup_retention(self):
        return self._retention


class TestBackupUseCase(unittest.TestCase):
    def test_no_snapshot_exists_creates_one(self):
        port = FakeBackupPort()
        result = BackupUseCase(port, FakeConfig(interval_minutes=15)).execute(now=1000.0)
        self.assertEqual(result.created, "store-1000.db.gz")
        self.assertEqual(port.pruned_with, 96)

    def test_newest_snapshot_younger_than_interval_is_a_noop(self):
        port = FakeBackupPort(snapshots=[("store-900.db.gz", 900.0)])
        result = BackupUseCase(port, FakeConfig(interval_minutes=15)).execute(now=1000.0)
        self.assertIsNone(result.created)
        self.assertEqual(result.pruned, [])
        self.assertEqual(port.created, [])

    def test_newest_snapshot_older_than_interval_creates_and_prunes(self):
        port = FakeBackupPort(
            snapshots=[("store-%d.db.gz" % i, float(i)) for i in range(5)][::-1]
        )
        result = BackupUseCase(port, FakeConfig(interval_minutes=15, retention=2)).execute(
            now=1000.0
        )
        self.assertEqual(result.created, "store-1000.db.gz")
        self.assertEqual(port.pruned_with, 2)
        self.assertEqual(len(result.pruned), 4)


if __name__ == "__main__":
    unittest.main()
