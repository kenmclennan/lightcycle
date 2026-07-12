import os
import unittest

from lightcycle.application.errors import UseCaseError
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


class _FakeGit:
    def __init__(self, git_repos=()):
        self._git_repos = set(git_repos)
        self.calls = []

    def is_git_repo(self, path):
        self.calls.append(("is_git_repo", path))
        return path in self._git_repos


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


class TestItemRepoNoFallback(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.svc = WorktreeService(
            self.store, git=None, fs=None, config=_Cfg("/home/u/workspace/projects")
        )

    def test_item_repo_returns_explicit_artifact(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)
        self.store.add_artifact(item, "repo", "saga")

        self.assertEqual(self.svc.item_repo(item), "saga")

    def test_item_repo_raises_when_no_repo_artifact(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)

        with self.assertRaises(UseCaseError):
            self.svc.item_repo(item)

    def test_has_repo_reflects_artifact_presence(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)

        self.assertFalse(self.svc.has_repo(item))
        self.store.add_artifact(item, "repo", "saga")
        self.assertTrue(self.svc.has_repo(item))


class TestEnsureNoSilentFailure(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()

    def test_ensure_returns_none_when_item_has_no_repo(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)
        git = _FakeGit()
        svc = WorktreeService(self.store, git, fs=None, config=_Cfg("/projects"))

        self.assertIsNone(svc.ensure(item))
        self.assertEqual(git.calls, [])

    def test_ensure_raises_when_repo_present_but_not_a_git_repo(self):
        theme = self.store.create_theme("theme")
        item = self.store.create_item("story", theme=theme)
        self.store.add_artifact(item, "repo", "saga")
        git = _FakeGit(git_repos=())
        svc = WorktreeService(self.store, git, fs=None, config=_Cfg("/projects"))

        with self.assertRaises(UseCaseError):
            svc.ensure(item)


if __name__ == "__main__":
    unittest.main()
