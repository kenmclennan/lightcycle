import os
import tempfile

from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.config import Config


def make_sqlite_store(now=None, extra_config=None):
    root = tempfile.mkdtemp()
    cfg_path = os.path.join(root, "config")
    with open(cfg_path, "w") as f:
        for k, v in (extra_config or {}).items():
            f.write("%s: %s\n" % (k, v))
    config = Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})
    return SqliteStore(config, now=now)


def plant_legacy_db(config, rows=()):
    from tests.support.legacy_store import plant_legacy_nodes

    store = SqliteStore(config)
    db_path = store._db_path
    store.release()
    plant_legacy_nodes(db_path, rows)
    return db_path
