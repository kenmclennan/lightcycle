import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from lightcycle.adapters.gitio import GitAdapter
from lightcycle.ports.git import GitReadError


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

    def test_raises_when_the_repo_cannot_be_read(self):
        not_a_repo = tempfile.mkdtemp()
        adapter = GitAdapter()

        with self.assertRaises(GitReadError):
            adapter.remote_url(not_a_repo)


class TestGitAdapterUnreadableWorktree(unittest.TestCase):
    def test_has_uncommitted_raises_when_the_repo_cannot_be_read(self):
        not_a_repo = tempfile.mkdtemp()

        with self.assertRaises(GitReadError):
            GitAdapter().has_uncommitted(not_a_repo)

    def test_worktree_registered_raises_when_the_repo_cannot_be_read(self):
        not_a_repo = tempfile.mkdtemp()

        with self.assertRaises(GitReadError):
            GitAdapter().worktree_registered(not_a_repo, os.path.join(not_a_repo, "wt"))

    def test_branch_exists_raises_when_the_repo_cannot_be_read(self):
        not_a_repo = tempfile.mkdtemp()

        with self.assertRaises(GitReadError):
            GitAdapter().branch_exists(not_a_repo, "main")

    def test_common_dir_raises_when_the_repo_cannot_be_read(self):
        not_a_repo = tempfile.mkdtemp()

        with self.assertRaises(GitReadError):
            GitAdapter().common_dir(not_a_repo)


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


class TestGitAdapterAddWorktree(unittest.TestCase):
    def test_creates_a_new_branch_and_worktree_when_base_is_given(self):
        repo = _make_repo()
        path = os.path.join(tempfile.mkdtemp(), "wt")
        adapter = GitAdapter()

        outcome = adapter.add_worktree(repo, path, "feat/x", "main", retries=0, backoff=0)

        self.assertTrue(outcome.ok)
        self.assertTrue(os.path.isdir(path))
        self.assertIn("feat/x", _git(repo, "branch", "--list", "feat/x").stdout)

    def test_attaches_to_an_existing_branch_without_creating_a_second_one(self):
        repo = _make_repo()
        _git(repo, "branch", "feat/existing")
        path = os.path.join(tempfile.mkdtemp(), "wt")
        adapter = GitAdapter()

        outcome = adapter.add_worktree(repo, path, "feat/existing", None, retries=0, backoff=0)

        self.assertTrue(outcome.ok)
        self.assertTrue(os.path.isdir(path))
        branches = _git(repo, "branch", "--list", "feat/existing").stdout.strip().splitlines()
        self.assertEqual(len(branches), 1)

    def test_returns_a_failed_outcome_when_the_target_path_is_not_a_worktree(self):
        repo = _make_repo()
        path = os.path.join(tempfile.mkdtemp(), "occupied")
        os.makedirs(path)
        (Path(path) / "file").write_text("in the way")
        adapter = GitAdapter()

        outcome = adapter.add_worktree(repo, path, "feat/x", "main", retries=0, backoff=0)

        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.detail)


class TestGitAdapterPruneWorktrees(unittest.TestCase):
    def test_prunes_a_stale_worktree_administrative_entry(self):
        repo = _make_repo()
        path = os.path.join(tempfile.mkdtemp(), "wt")
        _git(repo, "worktree", "add", path, "-b", "feat/x")
        shutil.rmtree(path)

        outcome = GitAdapter().prune_worktrees(repo)

        self.assertTrue(outcome.ok)
        self.assertNotIn(path, _git(repo, "worktree", "list").stdout)


class TestGitAdapterInitRepo(unittest.TestCase):
    def test_creates_a_fresh_repo_on_the_given_branch(self):
        project_dir = os.path.join(tempfile.mkdtemp(), "proj")
        os.makedirs(project_dir)

        outcome = GitAdapter().init_repo(project_dir, "main")

        self.assertTrue(outcome.ok)
        self.assertTrue(os.path.isdir(os.path.join(project_dir, ".git")))
        _git(project_dir, "config", "user.email", "t@t")
        _git(project_dir, "config", "user.name", "t")
        (Path(project_dir) / "README").write_text("x")
        _git(project_dir, "add", ".")
        _git(project_dir, "commit", "-q", "-m", "init")
        self.assertEqual(
            _git(project_dir, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(), "main"
        )


class TestGitAdapterSetBranchUpstream(unittest.TestCase):
    def test_sets_the_remote_and_merge_config_for_the_branch(self):
        repo = _make_repo()
        _git(repo, "branch", "feat/x")

        outcome = GitAdapter().set_branch_upstream(repo, "feat/x")

        self.assertTrue(outcome.ok)
        self.assertEqual(_git(repo, "config", "branch.feat/x.remote").stdout.strip(), "origin")
        self.assertEqual(
            _git(repo, "config", "branch.feat/x.merge").stdout.strip(), "refs/heads/feat/x"
        )


class TestGitAdapterCommitTracked(unittest.TestCase):
    def test_commits_a_modified_tracked_file(self):
        repo = _make_repo()
        (Path(repo) / "README").write_text("changed")
        adapter = GitAdapter()

        self.assertTrue(adapter.has_tracked_changes(repo))

        before = _git(repo, "rev-parse", "HEAD").stdout.strip()
        ok = adapter.commit_tracked(repo, "wip: preserved x1.1 on reclaim")
        after = _git(repo, "rev-parse", "HEAD").stdout.strip()

        self.assertTrue(ok)
        self.assertNotEqual(before, after)
        self.assertFalse(adapter.has_tracked_changes(repo))
        self.assertEqual(_git(repo, "status", "--porcelain").stdout.strip(), "")

    def test_ignores_a_purely_untracked_file(self):
        repo = _make_repo()
        (Path(repo) / "scratch.txt").write_text("new")
        adapter = GitAdapter()

        self.assertFalse(adapter.has_tracked_changes(repo))
        self.assertNotEqual(_git(repo, "status", "--porcelain").stdout.strip(), "")

        before = _git(repo, "rev-parse", "HEAD").stdout.strip()
        adapter.commit_tracked(repo, "wip: preserved x1.1 on reclaim")
        after = _git(repo, "rev-parse", "HEAD").stdout.strip()

        self.assertEqual(before, after)
        self.assertIn("??", _git(repo, "status", "--porcelain").stdout)

    def test_commits_only_the_tracked_change_leaving_untracked_files_alone(self):
        repo = _make_repo()
        (Path(repo) / "README").write_text("changed")
        (Path(repo) / "scratch.txt").write_text("new")
        adapter = GitAdapter()

        ok = adapter.commit_tracked(repo, "wip: preserved x1.1 on reclaim")

        self.assertTrue(ok)
        status = _git(repo, "status", "--porcelain").stdout
        self.assertIn("?? scratch.txt", status)
        self.assertNotIn("README", status)
        stat = _git(repo, "show", "--stat", "HEAD").stdout
        self.assertIn("README", stat)
        self.assertNotIn("scratch.txt", stat)


class TestGitAdapterRemoteHeadSha(unittest.TestCase):
    def test_returns_the_true_tip_even_when_the_local_clone_is_stale(self):
        origin = _bare_origin()
        publisher = _make_repo()
        _git(publisher, "remote", "add", "origin", origin)
        _git(publisher, "push", "-q", "origin", "HEAD:main")
        _git(publisher, "checkout", "-b", "feat/x")
        _git(publisher, "push", "-q", "origin", "feat/x")

        consumer = _clone(origin)

        (Path(publisher) / "NEW.md").write_text("a later push")
        _git(publisher, "add", "NEW.md")
        _git(publisher, "commit", "-q", "-m", "later push")
        _git(publisher, "push", "-q", "origin", "feat/x")
        true_tip = _git(publisher, "rev-parse", "feat/x").stdout.strip()

        sha = GitAdapter().remote_head_sha(consumer, "feat/x")

        self.assertEqual(sha, true_tip)

    def test_returns_none_when_the_branch_does_not_exist_on_the_remote(self):
        origin = _bare_origin()
        publisher = _make_repo()
        _git(publisher, "remote", "add", "origin", origin)
        _git(publisher, "push", "-q", "origin", "HEAD:main")
        consumer = _clone(origin)

        sha = GitAdapter().remote_head_sha(consumer, "no-such-branch")

        self.assertIsNone(sha)

    def test_touches_no_tracked_file_or_index_entry(self):
        origin = _bare_origin()
        publisher = _make_repo()
        _git(publisher, "remote", "add", "origin", origin)
        _git(publisher, "push", "-q", "origin", "HEAD:main")
        _git(publisher, "checkout", "-b", "feat/x")
        _git(publisher, "push", "-q", "origin", "feat/x")

        consumer = _clone(origin)
        before_status = _git(consumer, "status", "--porcelain").stdout

        GitAdapter().remote_head_sha(consumer, "feat/x")

        self.assertEqual(_git(consumer, "status", "--porcelain").stdout, before_status)


class TestGitAdapterRefSha(unittest.TestCase):
    def test_an_existing_ref_resolves_to_its_commit(self):
        repo = _make_repo()
        head = _git(repo, "rev-parse", "HEAD").stdout.strip()

        self.assertEqual(GitAdapter().ref_sha(repo, "main"), head)

    def test_a_missing_ref_is_none(self):
        self.assertIsNone(GitAdapter().ref_sha(_make_repo(), "origin/main"))

    def test_a_non_repository_root_raises_instead_of_reading_as_no_ref(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)

        with self.assertRaises(GitReadError):
            GitAdapter().ref_sha(root, "main")


class TestCommitAllIdentity(unittest.TestCase):
    def _no_identity_env(self):
        return mock.patch.dict(
            os.environ,
            {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": tempfile.mkdtemp()},
        )

    def test_reports_both_keys_missing_when_no_identity_configured(self):
        d = tempfile.mkdtemp()
        with self._no_identity_env():
            _git(d, "init", "-q", "-b", "main")

            self.assertEqual(GitAdapter().missing_identity(d), ["user.name", "user.email"])

    def test_reports_missing_identity_for_a_directory_that_does_not_exist_yet(self):
        d = tempfile.mkdtemp()
        with self._no_identity_env():
            self.assertEqual(
                GitAdapter().missing_identity(os.path.join(d, "later", "repo")),
                ["user.name", "user.email"],
            )

    def test_reports_nothing_missing_when_identity_configured(self):
        d = _make_repo()

        self.assertEqual(GitAdapter().missing_identity(d), [])

    def test_commit_all_fails_without_identity_and_invents_none(self):
        d = tempfile.mkdtemp()
        with self._no_identity_env():
            _git(d, "init", "-q", "-b", "main")
            _git(d, "config", "user.useConfigOnly", "true")
            (Path(d) / "README").write_text("x")

            self.assertFalse(GitAdapter().commit_all(d, "scaffold"))

    def test_keeps_configured_identity(self):
        d = _make_repo()
        (Path(d) / "more").write_text("y")

        self.assertTrue(GitAdapter().commit_all(d, "next"))
        self.assertEqual(_git(d, "log", "-1", "--format=%an").stdout.strip(), "t")


if __name__ == "__main__":
    unittest.main()


def _clone_of_origin(tmp):
    origin = os.path.join(tmp, "origin.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    clone = os.path.join(tmp, "clone")
    subprocess.run(["git", "clone", "-q", origin, clone], check=True, capture_output=True)
    for repo in (clone,):
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
    return origin, clone


def _commit(repo, path, text, message="c"):
    full = Path(repo) / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(text)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)


class TestGitAdapterGuidanceRef(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin, self.clone = _clone_of_origin(self.tmp)
        _commit(self.clone, "a.md", "origin-a")
        _commit(self.clone, ".hid/b.md", "hidden")
        _git(self.clone, "push", "-q", "origin", "main")
        self.adapter = GitAdapter()

    def test_default_ref_is_origin_main_when_origin_head_is_unset(self):
        self.assertEqual(self.adapter.default_ref(self.clone), "origin/main")

    def test_default_ref_follows_origin_head_when_set(self):
        _git(self.clone, "branch", "-q", "trunk")
        _git(self.clone, "push", "-q", "origin", "trunk")
        _git(self.clone, "fetch", "-q", "origin")
        _git(self.clone, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.assertEqual(self.adapter.default_ref(self.clone), "origin/trunk")

    def test_default_ref_is_local_main_without_a_remote(self):
        self.assertEqual(self.adapter.default_ref(_make_repo()), "main")

    def test_default_ref_is_none_for_a_remote_never_fetched(self):
        repo = _make_repo()
        _git(repo, "remote", "add", "origin", self.origin)
        self.assertIsNone(self.adapter.default_ref(repo))

    def test_default_ref_is_none_for_a_path_that_is_not_a_repo(self):
        self.assertIsNone(self.adapter.default_ref(tempfile.mkdtemp()))

    def test_reads_the_ref_not_the_checked_out_branch(self):
        _git(self.clone, "checkout", "-q", "-b", "feature")
        _commit(self.clone, "a.md", "branch-a")
        _commit(self.clone, "only-on-branch.md", "x")
        self.assertEqual(self.adapter.read_file_at(self.clone, "origin/main", "a.md"), b"origin-a")
        self.assertNotIn(
            "only-on-branch.md", self.adapter.list_files_at(self.clone, "origin/main"))

    def test_added_at_reads_the_earliest_adding_commit_of_a_path(self):
        added = self.adapter.added_at(self.clone, "origin/main", "a.md")
        self.assertRegex(added, r"^\d{4}-\d{2}-\d{2}T")
        self.assertIsNone(self.adapter.added_at(self.clone, "origin/main", "nope.md"))
        self.assertIsNone(self.adapter.added_at(self.clone, "origin/nope", "a.md"))

    def test_list_files_omits_dot_directories_and_is_sorted(self):
        _commit(self.clone, "z/c.md", "c")
        _git(self.clone, "push", "-q", "origin", "main")
        self.assertEqual(self.adapter.list_files_at(self.clone, "origin/main"), ["a.md", "z/c.md"])

    def test_read_file_at_returns_none_for_a_missing_path_or_ref(self):
        self.assertIsNone(self.adapter.read_file_at(self.clone, "origin/main", "nope.md"))
        self.assertIsNone(self.adapter.read_file_at(self.clone, "origin/nope", "a.md"))
        self.assertEqual(self.adapter.list_files_at(self.clone, "origin/nope"), [])

    def test_fetch_origin_makes_a_new_origin_commit_readable_without_a_checkout(self):
        other = os.path.join(self.tmp, "other")
        subprocess.run(["git", "clone", "-q", self.origin, other], check=True, capture_output=True)
        _git(other, "config", "user.email", "t@t")
        _git(other, "config", "user.name", "t")
        _commit(other, "new.md", "fresh")
        _git(other, "push", "-q", "origin", "main")
        self.assertIsNone(self.adapter.read_file_at(self.clone, "origin/main", "new.md"))
        outcome = self.adapter.fetch_origin(self.clone)
        self.assertTrue(outcome.ok)
        self.assertEqual(self.adapter.read_file_at(self.clone, "origin/main", "new.md"), b"fresh")
        self.assertFalse((Path(self.clone) / "new.md").exists())

    def test_a_failed_fetch_keeps_the_last_fetched_ref_readable(self):
        _git(self.clone, "remote", "set-url", "origin", os.path.join(self.tmp, "nonexistent.git"))
        outcome = self.adapter.fetch_origin(self.clone)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.detail)
        self.assertEqual(self.adapter.read_file_at(self.clone, "origin/main", "a.md"), b"origin-a")


class TestGitAdapterChangedPaths(unittest.TestCase):
    def test_reports_added_modified_and_deleted_rows_without_renames(self):
        repo = _make_repo()
        (Path(repo) / "gone.md").write_text("a")
        (Path(repo) / "kept.md").write_text("a")
        (Path(repo) / "moved.md").write_text("same content\nmore\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", "base")
        _git(repo, "checkout", "-q", "-b", "feature")
        (Path(repo) / "new.md").write_text("n")
        (Path(repo) / "kept.md").write_text("b")
        _git(repo, "rm", "-q", "gone.md")
        _git(repo, "mv", "moved.md", "renamed.md")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", "change")

        rows = GitAdapter().changed_paths(repo, "main")

        self.assertEqual(
            rows,
            [("D", "gone.md"), ("M", "kept.md"), ("D", "moved.md"),
             ("A", "new.md"), ("A", "renamed.md")],
        )

    def test_raises_for_an_unknown_base(self):
        repo = _make_repo()

        with self.assertRaises(GitReadError):
            GitAdapter().changed_paths(repo, "no-such-ref")
