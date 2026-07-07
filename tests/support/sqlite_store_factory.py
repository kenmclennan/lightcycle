import os
import tempfile

from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.config import Config


def make_sqlite_store(shortcode="GRID", now=None):
    root = tempfile.mkdtemp()
    cfg_path = os.path.join(root, "config")
    with open(cfg_path, "w") as f:
        f.write("shortcode: %s\n" % shortcode)
    config = Config(environ={"LC_ROOT_OVERRIDE": root, "LC_CONFIG": cfg_path})
    return SqliteStore(config, now=now)
