import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from lightcycle.adapters.fsio import ensure_worktrees_ignored
from lightcycle.adapters.gitio import GitAdapter


def _git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, check=True)


def _make_repo():
    d = tempfile.mkdtemp()
    _git(d, "init", "-q", "-b", "main")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    (Path(d) / "README").write_text("x")
    _git(d, "add", ".")
    _git(d, "commit", "-q", "-m", "init")
    return d


def _common_dir(repo):
    return GitAdapter().common_dir(repo)


class TestEnsureWorktreesIgnored(unittest.TestCase):
    def test_no_gitignore_is_created_and_the_working_tree_stays_clean(self):
        repo = _make_repo()

        ensure_worktrees_ignored(_common_dir(repo))

        self.assertFalse((Path(repo) / ".gitignore").exists())
        self.assertEqual(_git(repo, "status", "--porcelain").stdout, "")
        exclude = (Path(repo) / ".git" / "info" / "exclude").read_text().splitlines()
        self.assertIn(".worktrees/", [l.strip() for l in exclude])

    def test_existing_tracked_gitignore_is_left_byte_identical(self):
        repo = _make_repo()
        gitignore = Path(repo) / ".gitignore"
        gitignore.write_text("*.pyc\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-q", "-m", "add gitignore")
        before = gitignore.read_bytes()

        ensure_worktrees_ignored(_common_dir(repo))

        self.assertEqual(gitignore.read_bytes(), before)
        self.assertEqual(_git(repo, "status", "--porcelain").stdout, "")

    def test_existing_info_exclude_content_survives_the_append(self):
        repo = _make_repo()
        exclude = Path(repo) / ".git" / "info" / "exclude"
        exclude.write_text("# git ls-files --others --exclude-from=.git/info/exclude\nnotes.local\n")

        ensure_worktrees_ignored(_common_dir(repo))

        lines = [l.strip() for l in exclude.read_text().splitlines()]
        self.assertIn("# git ls-files --others --exclude-from=.git/info/exclude", lines)
        self.assertIn("notes.local", lines)
        self.assertIn(".worktrees/", lines)

    def test_called_twice_does_not_duplicate_the_line(self):
        repo = _make_repo()

        ensure_worktrees_ignored(_common_dir(repo))
        ensure_worktrees_ignored(_common_dir(repo))

        exclude = Path(repo) / ".git" / "info" / "exclude"
        lines = [l.strip() for l in exclude.read_text().splitlines()]
        self.assertEqual(lines.count(".worktrees/"), 1)

    def test_creates_the_info_directory_when_absent(self):
        repo = _make_repo()
        info_dir = Path(repo) / ".git" / "info"
        for entry in info_dir.iterdir():
            entry.unlink()
        info_dir.rmdir()

        ensure_worktrees_ignored(_common_dir(repo))

        exclude = info_dir / "exclude"
        self.assertTrue(exclude.exists())
        self.assertIn(".worktrees/", [l.strip() for l in exclude.read_text().splitlines()])


class TestCommonDirFromALinkedWorktree(unittest.TestCase):
    def test_resolves_to_the_shared_git_dir_not_the_worktrees_private_one(self):
        repo = _make_repo()
        wt = Path(tempfile.mkdtemp()) / "wt"
        _git(repo, "worktree", "add", "-b", "feature", str(wt))

        main_common_dir = os.path.realpath(_common_dir(repo))
        wt_common_dir = os.path.realpath(_common_dir(str(wt)))

        self.assertEqual(main_common_dir, wt_common_dir)

    def test_ignoring_worktrees_from_inside_a_linked_worktree_is_visible_from_the_main_checkout(self):
        repo = _make_repo()
        wt = Path(tempfile.mkdtemp()) / "wt"
        _git(repo, "worktree", "add", "-b", "feature", str(wt))

        ensure_worktrees_ignored(_common_dir(str(wt)))

        exclude = Path(repo) / ".git" / "info" / "exclude"
        self.assertIn(".worktrees/", [l.strip() for l in exclude.read_text().splitlines()])


if __name__ == "__main__":
    unittest.main()
