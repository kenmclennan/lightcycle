import unittest

from lightcycle.domain.workspace.isolation import refuses_live_store


class TestRefusesLiveStore(unittest.TestCase):
    def test_worktree_checkout_under_a_project_repo_against_live_root_refuses(self):
        self.assertTrue(refuses_live_store(
            package_root="/home/u/workspace/projects/lightcycle/.worktrees/LC-13.1/lightcycle",
            live_store_root="/home/u/.lightcycle",
            target_root="/home/u/.lightcycle",
        ))

    def test_deployed_package_against_live_root_allows(self):
        self.assertFalse(refuses_live_store(
            package_root="/home/u/.local/pipx/venvs/lightcycle/lib/site-packages",
            live_store_root="/home/u/.lightcycle",
            target_root="/home/u/.lightcycle",
        ))

    def test_worktree_checkout_against_sandbox_root_allows(self):
        self.assertFalse(refuses_live_store(
            package_root="/home/u/workspace/projects/lightcycle/.worktrees/LC-13.1/lightcycle",
            live_store_root="/home/u/.lightcycle",
            target_root="/tmp/sandbox-store",
        ))

    def test_worktrees_component_under_any_project_repo_still_refuses(self):
        self.assertTrue(refuses_live_store(
            package_root="/home/u/workspace/projects/saga/.worktrees/tg-17.1/saga/sub",
            live_store_root="/home/u/.lightcycle",
            target_root="/home/u/.lightcycle",
        ))

    def test_lookalike_dir_name_is_not_treated_as_a_worktrees_component(self):
        self.assertFalse(refuses_live_store(
            package_root="/home/u/workspace/projects/lightcycle/.worktrees-other/lightcycle",
            live_store_root="/home/u/.lightcycle",
            target_root="/home/u/.lightcycle",
        ))


if __name__ == "__main__":
    unittest.main()
