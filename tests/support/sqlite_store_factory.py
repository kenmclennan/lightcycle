import os
import tempfile

from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.config import Config


def make_sqlite_store(shortcode="GRID", now=None):
    root = tempfile.mkdtemp()
    cfg_path = os.path.join(root, "config")
    with open(cfg_path, "w") as f:
        f.write("shortcode: %s\n" % shortcode)
    config = Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})
    return SqliteStore(config, now=now)


def make_legacy_sqlite_store(rows, artifacts=(), shortcode="GRID"):
    from tests.support.legacy_store import plant_legacy_nodes

    root = tempfile.mkdtemp()
    cfg_path = os.path.join(root, "config")
    with open(cfg_path, "w") as f:
        f.write("shortcode: %s\n" % shortcode)
    config = Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})
    store = SqliteStore(config)
    db_path = store._db_path
    store.disconnect()
    plant_legacy_nodes(db_path, rows, artifacts)
    return SqliteStore(config)


def plant_legacy_db(config, rows=(), artifacts=()):
    from tests.support.legacy_store import plant_legacy_nodes

    store = SqliteStore(config)
    db_path = store._db_path
    store.disconnect()
    plant_legacy_nodes(db_path, rows, artifacts)
    return db_path
