import unittest

from lightcycle.domain.workspace.isolation import refuses_live_store


class TestRefusesLiveStore(unittest.TestCase):
    def test_worktree_package_against_live_root_refuses(self):
        self.assertTrue(refuses_live_store(
            package_root="/home/u/.lightcycle/.worktrees/LC-13.1/lightcycle",
            worktrees_dir="/home/u/.lightcycle/.worktrees",
            target_root="/home/u/.lightcycle",
        ))

    def test_deployed_package_against_live_root_allows(self):
        self.assertFalse(refuses_live_store(
            package_root="/home/u/.local/pipx/venvs/lightcycle/lib/site-packages",
            worktrees_dir="/home/u/.lightcycle/.worktrees",
            target_root="/home/u/.lightcycle",
        ))

    def test_worktree_package_against_sandbox_root_allows(self):
        self.assertFalse(refuses_live_store(
            package_root="/home/u/.lightcycle/.worktrees/LC-13.1/lightcycle",
            worktrees_dir="/home/u/.lightcycle/.worktrees",
            target_root="/tmp/sandbox-store",
        ))

    def test_package_root_equal_to_worktrees_dir_counts_as_under_it(self):
        self.assertTrue(refuses_live_store(
            package_root="/home/u/.lightcycle/.worktrees",
            worktrees_dir="/home/u/.lightcycle/.worktrees",
            target_root="/home/u/.lightcycle",
        ))

    def test_lookalike_sibling_path_is_not_treated_as_under_worktrees_dir(self):
        self.assertFalse(refuses_live_store(
            package_root="/home/u/.lightcycle/.worktrees-other/lightcycle",
            worktrees_dir="/home/u/.lightcycle/.worktrees",
            target_root="/home/u/.lightcycle",
        ))


if __name__ == "__main__":
    unittest.main()
