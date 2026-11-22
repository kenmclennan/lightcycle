import os
import shutil
import subprocess
import tempfile
import unittest

from lightcycle.application.setup.project_relocate import RelocateProjectUseCase
from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.gitio import GitAdapter
from tests.support.fake_store import FakeStore


def git(root, *args):
    return subprocess.run(
        ["git", "-C", root, *args], capture_output=True, text=True, timeout=60, check=True
    )


class _Config:
    def __init__(self, root):
        self._root = root

    def data_root(self):
        return self._root

    def home_dir(self):
        return "/nonexistent-home"

    def load_config(self):
        return {}


class _Edit:
    def set(self, key, values):
        raise AssertionError("no config should be rewritten")


class _Worktrees:
    def target_repo(self, step):
        raise AssertionError("no step is claimed")


class TestRealGitMove(unittest.TestCase):
    def test_real_git_move_keeps_every_worktree_working(self):
        base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        old = os.path.join(base, "old")
        outside = os.path.join(base, "outside-wt")
        home = os.path.join(base, "home")
        os.makedirs(old)
        os.makedirs(home)
        git(old, "init", "-q", "-b", "main")
        git(old, "config", "user.email", "t@example.com")
        git(old, "config", "user.name", "t")
        git(old, "commit", "-q", "--allow-empty", "-m", "init")
        git(old, "worktree", "add", "-q", os.path.join(old, ".worktrees", "a"), "-b", "a")
        git(old, "worktree", "add", "-q", os.path.join(old, ".claude", "worktrees", "b"), "-b", "b")
        git(old, "worktree", "add", "-q", outside, "-b", "c")
        store = FakeStore()
        store.add_project("acme/app", shortcode="APP", local_path=old)
        config = _Config(home)
        uc = RelocateProjectUseCase(
            store, GitAdapter(), FsAdapter(config), config, _Edit(), _Worktrees()
        )
        new = os.path.join(base, "new")
        uc.move("acme/app", new)
        self.assertEqual(store.get_project("acme/app").local_path, new)
        for wt in (
            os.path.join(new, ".worktrees", "a"),
            os.path.join(new, ".claude", "worktrees", "b"),
            outside,
        ):
            self.assertEqual(git(wt, "status", "--porcelain").returncode, 0)
        listing = git(new, "worktree", "list", "--porcelain").stdout
        self.assertNotIn("prunable", listing)
        git(new, "worktree", "prune", "-v")
        self.assertEqual(git(new, "worktree", "list", "--porcelain").stdout, listing)


if __name__ == "__main__":
    unittest.main()
