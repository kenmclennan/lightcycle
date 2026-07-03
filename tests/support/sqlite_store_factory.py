import os
import tempfile

from the_grid.adapters.sqlite_store import SqliteStore
from the_grid.config import Config


def make_sqlite_store(shortcode="GRID"):
    root = tempfile.mkdtemp()
    cfg_path = os.path.join(root, "config")
    with open(cfg_path, "w") as f:
        f.write("shortcode: %s\n" % shortcode)
    config = Config(environ={"GRID_ROOT_OVERRIDE": root, "GRID_CONFIG": cfg_path})
    return SqliteStore(config)
