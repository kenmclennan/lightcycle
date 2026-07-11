import os
import tempfile
import unittest

from lightcycle.adapters.sqlite_store import LiveStoreRefused, SqliteStore
from lightcycle.config import Config


def _config(root):
    cfg_path = os.path.join(root, "config")
    with open(cfg_path, "w") as f:
        f.write("shortcode: GRID\n")
    return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})


class TestSqliteStoreRefusesLiveStoreFromWorktree(unittest.TestCase):
    def test_worktree_package_under_a_project_repo_against_the_live_home_refuses(self):
        home = tempfile.mkdtemp()
        project_repo = tempfile.mkdtemp()
        package_root = os.path.join(project_repo, ".worktrees", "LC-13.1", "lightcycle")

        with self.assertRaises(LiveStoreRefused):
            SqliteStore(_config(home), package_root=package_root, default_data_root=home)

        self.assertFalse(os.path.exists(os.path.join(home, "store.db")))

    def test_non_worktree_package_against_the_same_home_succeeds(self):
        home = tempfile.mkdtemp()
        package_root = os.path.join(home, "checkout", "lightcycle")

        SqliteStore(_config(home), package_root=package_root, default_data_root=home)

        self.assertTrue(os.path.exists(os.path.join(home, "store.db")))

    def test_worktree_package_under_a_project_repo_against_a_sandbox_root_succeeds(self):
        home = tempfile.mkdtemp()
        sandbox = tempfile.mkdtemp()
        project_repo = tempfile.mkdtemp()
        package_root = os.path.join(project_repo, ".worktrees", "LC-13.1", "lightcycle")

        SqliteStore(_config(sandbox), package_root=package_root, default_data_root=home)

        self.assertTrue(os.path.exists(os.path.join(sandbox, "store.db")))


if __name__ == "__main__":
    unittest.main()
