import os
import tempfile
import unittest

from lightcycle.adapters.sqlite_store import LiveStoreRefused, SqliteStore
from lightcycle.config import Config


def _config(root):
    cfg_path = os.path.join(root, "config")
    with open(cfg_path, "w") as f:
        f.write("shortcode: GRID\n")
    return Config(environ={"LC_ROOT_OVERRIDE": root, "LC_CONFIG": cfg_path})


class TestSqliteStoreRefusesLiveStoreFromWorktree(unittest.TestCase):
    def test_worktree_package_against_the_home_it_belongs_to_refuses(self):
        home = tempfile.mkdtemp()
        worktrees_dir = os.path.join(home, ".worktrees")
        package_root = os.path.join(worktrees_dir, "LC-13.1", "lightcycle")

        with self.assertRaises(LiveStoreRefused):
            SqliteStore(_config(home), package_root=package_root, worktrees_dir=worktrees_dir)

        self.assertFalse(os.path.exists(os.path.join(home, "store.db")))

    def test_non_worktree_package_against_the_same_home_succeeds(self):
        home = tempfile.mkdtemp()
        worktrees_dir = os.path.join(home, ".worktrees")
        package_root = os.path.join(home, "checkout", "lightcycle")

        SqliteStore(_config(home), package_root=package_root, worktrees_dir=worktrees_dir)

        self.assertTrue(os.path.exists(os.path.join(home, "store.db")))

    def test_worktree_package_against_a_sandbox_root_succeeds(self):
        home = tempfile.mkdtemp()
        worktrees_dir = os.path.join(home, ".worktrees")
        sandbox = tempfile.mkdtemp()
        package_root = os.path.join(worktrees_dir, "LC-13.1", "lightcycle")

        SqliteStore(_config(sandbox), package_root=package_root, worktrees_dir=worktrees_dir)

        self.assertTrue(os.path.exists(os.path.join(sandbox, "store.db")))


if __name__ == "__main__":
    unittest.main()
