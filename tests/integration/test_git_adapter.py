import os
import subprocess
import tempfile
import unittest
from pathlib import Path

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


class TestGitAdapterRemoteUrl(unittest.TestCase):
    def test_returns_origin_url_when_configured(self):
        repo = _make_repo()
        _git(repo, "remote", "add", "origin", "git@github.com:x/specs.git")
        adapter = GitAdapter()

        self.assertEqual(adapter.remote_url(repo), "git@github.com:x/specs.git")

    def test_returns_none_when_no_origin_configured(self):
        repo = _make_repo()
        adapter = GitAdapter()

        self.assertIsNone(adapter.remote_url(repo))


def _bare_origin():
    d = tempfile.mkdtemp()
    _git(d, "init", "-q", "-b", "main", "--bare")
    return d


def _clone(origin):
    d = tempfile.mkdtemp()
    subprocess.run(["git", "clone", "-q", origin, d], check=True, capture_output=True)
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    return d


class TestGitAdapterSyncToOrigin(unittest.TestCase):
    def test_sync_pulls_a_newly_merged_file_into_the_consumer_checkout(self):
        origin = _bare_origin()
        publisher = _make_repo()
        _git(publisher, "remote", "add", "origin", origin)
        _git(publisher, "push", "-q", "origin", "HEAD:main")

        consumer = _clone(origin)

        (Path(publisher) / "NEW.md").write_text("merged spec")
        _git(publisher, "add", "NEW.md")
        _git(publisher, "commit", "-q", "-m", "add spec")
        _git(publisher, "push", "-q", "origin", "main")

        ok = GitAdapter().sync_to_origin(consumer)

        self.assertTrue(ok)
        self.assertTrue((Path(consumer) / "NEW.md").exists())

    def test_sync_fails_loud_and_leaves_a_diverged_local_commit_untouched(self):
        origin = _bare_origin()
        publisher = _make_repo()
        _git(publisher, "remote", "add", "origin", origin)
        _git(publisher, "push", "-q", "origin", "HEAD:main")

        consumer = _clone(origin)

        (Path(consumer) / "LOCAL.md").write_text("local only")
        _git(consumer, "add", "LOCAL.md")
        _git(consumer, "commit", "-q", "-m", "local change")
        local_sha = _git(consumer, "rev-parse", "HEAD").stdout.strip()

        (Path(publisher) / "NEW.md").write_text("merged spec")
        _git(publisher, "add", "NEW.md")
        _git(publisher, "commit", "-q", "-m", "add spec")
        _git(publisher, "push", "-q", "origin", "main")

        ok = GitAdapter().sync_to_origin(consumer)

        self.assertFalse(ok)
        self.assertEqual(_git(consumer, "rev-parse", "HEAD").stdout.strip(), local_sha)
        self.assertTrue((Path(consumer) / "LOCAL.md").exists())


class TestGitAdapterClone(unittest.TestCase):
    def test_clone_creates_a_working_copy_from_a_bare_origin(self):
        origin = _bare_origin()
        publisher = _make_repo()
        _git(publisher, "remote", "add", "origin", origin)
        _git(publisher, "push", "-q", "origin", "HEAD:main")
        dest = os.path.join(tempfile.mkdtemp(), "nested", "specs")

        ok = GitAdapter().clone(origin, dest)

        self.assertTrue(ok)
        self.assertTrue((Path(dest) / "README").exists())


class TestGitAdapterSyncToDefaultBranch(unittest.TestCase):
    def test_brings_a_checkout_on_a_stale_branch_up_to_the_merged_default_branch(self):
        origin = _bare_origin()
        publisher = _make_repo()
        _git(publisher, "remote", "add", "origin", origin)
        _git(publisher, "push", "-q", "origin", "HEAD:main")
        consumer = _clone(origin)
        _git(consumer, "checkout", "-q", "-b", "some-other-branch")

        (Path(publisher) / "NEW.md").write_text("merged spec")
        _git(publisher, "add", "NEW.md")
        _git(publisher, "commit", "-q", "-m", "add spec")
        _git(publisher, "push", "-q", "origin", "main")

        ok = GitAdapter().sync_to_default_branch(consumer)

        self.assertTrue(ok)
        self.assertEqual(_git(consumer, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(), "main")
        self.assertTrue((Path(consumer) / "NEW.md").exists())

    def test_fails_loud_and_preserves_uncommitted_changes_when_checkout_would_clobber(self):
        origin = _bare_origin()
        publisher = _make_repo()
        _git(publisher, "remote", "add", "origin", origin)
        _git(publisher, "push", "-q", "origin", "HEAD:main")
        consumer = _clone(origin)
        _git(consumer, "checkout", "-q", "-b", "some-other-branch")
        (Path(consumer) / "README").write_text("uncommitted local edit")

        (Path(publisher) / "README").write_text("conflicting merged edit")
        _git(publisher, "add", "README")
        _git(publisher, "commit", "-q", "-m", "edit readme")
        _git(publisher, "push", "-q", "origin", "main")

        ok = GitAdapter().sync_to_default_branch(consumer)

        self.assertFalse(ok)
        self.assertEqual(_git(consumer, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
                         "some-other-branch")
        self.assertEqual((Path(consumer) / "README").read_text(), "uncommitted local edit")

    def test_fails_loud_and_leaves_a_diverged_local_default_branch_untouched(self):
        origin = _bare_origin()
        publisher = _make_repo()
        _git(publisher, "remote", "add", "origin", origin)
        _git(publisher, "push", "-q", "origin", "HEAD:main")
        consumer = _clone(origin)
        (Path(consumer) / "LOCAL.md").write_text("local only")
        _git(consumer, "add", "LOCAL.md")
        _git(consumer, "commit", "-q", "-m", "local change")
        local_sha = _git(consumer, "rev-parse", "HEAD").stdout.strip()

        (Path(publisher) / "NEW.md").write_text("merged spec")
        _git(publisher, "add", "NEW.md")
        _git(publisher, "commit", "-q", "-m", "add spec")
        _git(publisher, "push", "-q", "origin", "main")

        ok = GitAdapter().sync_to_default_branch(consumer)

        self.assertFalse(ok)
        self.assertEqual(_git(consumer, "rev-parse", "HEAD").stdout.strip(), local_sha)
        self.assertTrue((Path(consumer) / "LOCAL.md").exists())


class TestGitAdapterCommitAll(unittest.TestCase):
    def test_commit_all_commits_a_dirty_worktree(self):
        repo = _make_repo()
        (Path(repo) / "f.txt").write_text("wip")
        adapter = GitAdapter()

        self.assertTrue(adapter.has_uncommitted(repo))

        before = _git(repo, "rev-parse", "HEAD").stdout.strip()
        ok = adapter.commit_all(repo, "wip: preserved x1.1 on reclaim")
        after = _git(repo, "rev-parse", "HEAD").stdout.strip()

        self.assertTrue(ok)
        self.assertNotEqual(before, after)
        self.assertEqual(_git(repo, "status", "--porcelain").stdout.strip(), "")
        self.assertFalse(adapter.has_uncommitted(repo))


if __name__ == "__main__":
    unittest.main()
