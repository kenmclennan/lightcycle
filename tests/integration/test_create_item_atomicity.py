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
        config = Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})
        store = SqliteStore(config)
        store.add_project("acme/app", shortcode="GRID")

        with self.assertRaises(UseCaseError):
            CreateItemUseCase(store).execute(
                CreateItemInput(
                    title="t", description="d", project="app", backlog=["does-not-exist"]
                )
            )

        self.assertEqual(store.all_nodes(), [])


if __name__ == "__main__":
    unittest.main()
