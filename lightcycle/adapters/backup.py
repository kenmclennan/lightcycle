import datetime
import gzip
import os
import sqlite3

from lightcycle.ports.backup import BackupPort

_DB_FILENAME = "store.db"
_PREFIX = "store-"
_SUFFIX = ".db.gz"


def _snapshot_name(now):
    ts = datetime.datetime.utcfromtimestamp(now).strftime("%Y%m%dT%H%M%SZ")
    return "%s%s%s" % (_PREFIX, ts, _SUFFIX)


class SqliteBackupAdapter(BackupPort):
    def __init__(self, config):
        self._config = config

    def _backups_dir(self):
        return self._config.backups_dir()

    def _store_path(self):
        return os.path.join(self._config.data_root(), _DB_FILENAME)

    def list_snapshots(self):
        d = self._backups_dir()
        if not os.path.isdir(d):
            return []
        names = sorted(
            (n for n in os.listdir(d) if n.startswith(_PREFIX) and n.endswith(_SUFFIX)),
            reverse=True,
        )
        return [(n, os.path.getmtime(os.path.join(d, n))) for n in names]

    def create_snapshot(self, now):
        d = self._backups_dir()
        os.makedirs(d, exist_ok=True)
        name = _snapshot_name(now)
        final_path = os.path.join(d, name)
        tmp_db = "%s.%d.tmp" % (final_path, os.getpid())
        live = sqlite3.connect(self._store_path())
        try:
            scratch = sqlite3.connect(tmp_db)
            try:
                live.backup(scratch)
            finally:
                scratch.close()
        finally:
            live.close()
        tmp_gz = "%s.%d.gz.tmp" % (final_path, os.getpid())
        with open(tmp_db, "rb") as src, gzip.open(tmp_gz, "wb") as dst:
            dst.write(src.read())
        os.remove(tmp_db)
        os.replace(tmp_gz, final_path)
        return name

    def prune(self, keep):
        removed = []
        for name, _mtime in self.list_snapshots()[keep:]:
            os.remove(os.path.join(self._backups_dir(), name))
            removed.append(name)
        return removed

    def restore(self, name):
        d = self._backups_dir()
        target = name
        if target is None:
            snapshots = self.list_snapshots()
            if not snapshots:
                raise FileNotFoundError("no snapshots in %s" % d)
            target = snapshots[0][0]
        src = os.path.join(d, target)
        store_path = self._store_path()
        tmp_db = "%s.%d.tmp" % (store_path, os.getpid())
        with gzip.open(src, "rb") as f_in, open(tmp_db, "wb") as f_out:
            f_out.write(f_in.read())
        conn = sqlite3.connect(tmp_db)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError:
            result = None
        finally:
            conn.close()
        if not result or result[0] != "ok":
            os.remove(tmp_db)
            raise ValueError("snapshot %s failed integrity check" % target)
        os.replace(tmp_db, store_path)
        for ext in ("-wal", "-shm"):
            sidecar = store_path + ext
            if os.path.exists(sidecar):
                os.remove(sidecar)
