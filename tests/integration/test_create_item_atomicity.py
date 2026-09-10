import os
import tempfile
import unittest

from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.create_item import CreateItemInput, CreateItemUseCase
from lightcycle.config import Config


class TestCreateItemAtomicity(unittest.TestCase):
    def test_an_unresolvable_backlog_id_leaves_no_item_in_the_store(self):
        root = tempfile.mkdtemp()
        cfg_path = os.path.join(root, "config")
        with open(cfg_path, "w") as f:
            f.write("shortcode: GRID\n")
        config = Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})
        store = SqliteStore(config)

        with self.assertRaises(UseCaseError):
            CreateItemUseCase(store, config).execute(
                CreateItemInput(title="t", description="d", backlog=["does-not-exist"])
            )

        self.assertEqual(store.all_nodes(), [])


if __name__ == "__main__":
    unittest.main()
