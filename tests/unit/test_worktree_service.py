import os
import unittest

from lightcycle.application.services.worktree import WorktreeService
from tests.support.fake_store import FakeStore


class _Cfg:
    def __init__(self, projects_root, engine_root="lightcycle"):
        self._projects_root = projects_root
        self._engine_root = engine_root

    def projects_root(self):
        return self._projects_root

    def engine_root(self):
        return self._engine_root


class TestWorktreePath(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.svc = WorktreeService(
            self.store, git=None, fs=None, config=_Cfg("/home/u/workspace/projects")
        )

    def test_resolves_under_the_items_target_repo_not_data_root(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)
        self.store.add_artifact(item, "repo", "saga")

        path = self.svc.worktree_path(item)

        self.assertEqual(
            path, os.path.join("/home/u/workspace/projects", "saga", ".worktrees", item)
        )

    def test_two_items_with_different_repos_resolve_under_their_own_repos(self):
        theme = self.store.create_theme("theme")
        saga_item = self.store.create_item("saga story", theme=theme)
        self.store.add_artifact(saga_item, "repo", "saga")
        horde_item = self.store.create_item("horde story", theme=theme)
        self.store.add_artifact(horde_item, "repo", "horde")

        saga_path = self.svc.worktree_path(saga_item)
        horde_path = self.svc.worktree_path(horde_item)

        self.assertEqual(
            os.path.dirname(os.path.dirname(saga_path)),
            os.path.join("/home/u/workspace/projects", "saga"),
        )
        self.assertEqual(
            os.path.dirname(os.path.dirname(horde_path)),
            os.path.join("/home/u/workspace/projects", "horde"),
        )


if __name__ == "__main__":
    unittest.main()
