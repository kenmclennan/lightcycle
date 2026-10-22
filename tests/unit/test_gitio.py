import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from lightcycle.adapters import gitio
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.ports.git import GitReadError


def _proc(returncode=0, stdout="", stderr=""):
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


class TestIsLockContention(unittest.TestCase):
    def test_transient_lock_errors_are_contention(self):
        self.assertTrue(gitio.is_lock_contention("fatal: could not lock working tree"))
        self.assertTrue(
            gitio.is_lock_contention(
                "Unable to create '/r/.git/worktrees/x/index.lock': File exists"
            )
        )
        self.assertTrue(gitio.is_lock_contention("fatal: 'x' is already locked"))

    def test_real_errors_are_not_contention(self):
        self.assertFalse(gitio.is_lock_contention("fatal: invalid reference: origin/main"))
        self.assertFalse(gitio.is_lock_contention(""))
        self.assertFalse(gitio.is_lock_contention(None))


class TestRemoteUrl(unittest.TestCase):
    def _run(self, is_repo, remote_result):
        def side_effect(args, **kwargs):
            if "rev-parse" in args and "--git-dir" in args:
                return _proc(0 if is_repo else 1)
            return remote_result

        return side_effect

    def test_raises_when_root_is_not_a_readable_git_repo(self):
        with patch(
            "lightcycle.adapters.gitio.subprocess.run",
            side_effect=self._run(is_repo=False, remote_result=_proc(1)),
        ):
            with self.assertRaises(GitReadError):
                gitio.remote_url("/repo")

    def test_returns_none_when_no_origin_is_configured(self):
        with patch(
            "lightcycle.adapters.gitio.subprocess.run",
            side_effect=self._run(
                is_repo=True,
                remote_result=_proc(2, stderr="error: No such remote 'origin'\n"),
            ),
        ):
            self.assertIsNone(gitio.remote_url("/repo"))

    def test_raises_when_git_fails_for_a_reason_other_than_missing_origin(self):
        with patch(
            "lightcycle.adapters.gitio.subprocess.run",
            side_effect=self._run(is_repo=True, remote_result=_proc(128, stderr="fatal: boom\n")),
        ):
            with self.assertRaises(GitReadError):
                gitio.remote_url("/repo")


class TestWorktreeBase(unittest.TestCase):
    def test_raises_when_root_is_not_a_readable_git_repo(self):
        with patch("lightcycle.adapters.gitio.subprocess.run", return_value=_proc(1)):
            with self.assertRaises(GitReadError):
                gitio.worktree_base("/repo")

    def test_returns_none_when_neither_base_ref_exists(self):
        def side_effect(args, **kwargs):
            if "rev-parse" in args and "--git-dir" in args:
                return _proc(0)
            return _proc(1)

        with patch("lightcycle.adapters.gitio.subprocess.run", side_effect=side_effect):
            self.assertIsNone(gitio.worktree_base("/repo"))

    def test_returns_the_first_base_ref_found(self):
        def side_effect(args, **kwargs):
            if "rev-parse" in args and "--git-dir" in args:
                return _proc(0)
            if "refs/remotes/origin/main" in args:
                return _proc(0)
            return _proc(1)

        with patch("lightcycle.adapters.gitio.subprocess.run", side_effect=side_effect):
            self.assertEqual(gitio.worktree_base("/repo"), "origin/main")


class TestDeleteRemoteBranch(unittest.TestCase):
    def test_attempts_delete_without_local_tracking_ref(self):
        def side_effect(args, **kwargs):
            if "rev-parse" in args:
                return _proc(1)
            return _proc(0)

        with patch("lightcycle.adapters.gitio.subprocess.run", side_effect=side_effect) as mock_run:
            gitio.delete_remote_branch("/repo", "feat/no-tracking-ref")
            push_calls = [c for c in mock_run.call_args_list if "--delete" in c.args[0]]
            self.assertEqual(len(push_calls), 1)
            self.assertIn("feat/no-tracking-ref", push_calls[0].args[0])

    def test_tolerates_push_failure_when_remote_already_gone(self):
        with patch("lightcycle.adapters.gitio.subprocess.run", return_value=_proc(1)):
            outcome = gitio.delete_remote_branch("/repo", "feat/auto-deleted")
        self.assertFalse(outcome.ok)

    def test_ok_for_exit_zero_and_for_a_ref_that_does_not_exist(self):
        with patch("lightcycle.adapters.gitio.subprocess.run", return_value=_proc(0)):
            self.assertTrue(gitio.delete_remote_branch("/repo", "b").ok)
        gone = _proc(1, stderr="error: unable to delete 'b': remote ref does not exist")
        with patch("lightcycle.adapters.gitio.subprocess.run", return_value=gone):
            self.assertTrue(gitio.delete_remote_branch("/repo", "b").ok)

    def test_not_ok_carries_the_stderr(self):
        refused = _proc(128, stderr="fatal: 'origin' does not appear to be a git repository\n")
        with patch("lightcycle.adapters.gitio.subprocess.run", return_value=refused):
            outcome = gitio.delete_remote_branch("/repo", "b")
        self.assertFalse(outcome.ok)
        self.assertIn("does not appear to be a git repository", outcome.detail)


class TestRemoveWorktree(unittest.TestCase):
    def _run(self, remove_proc):
        def side_effect(args, **kwargs):
            if "remove" in args:
                if isinstance(remove_proc, Exception):
                    raise remove_proc
                return remove_proc
            return _proc(0)

        return patch("lightcycle.adapters.gitio.subprocess.run", side_effect=side_effect)

    def test_raises_with_stderr_on_nonzero_exit(self):
        with self._run(_proc(128, stderr="fatal: cannot remove a locked working tree")):
            with self.assertRaises(GitReadError) as ctx:
                gitio.remove_worktree("/repo", "/repo/.worktrees/x")
        self.assertIn("cannot remove a locked working tree", str(ctx.exception))

    def test_raises_on_timeout(self):
        with self._run(subprocess.TimeoutExpired(cmd="git", timeout=30)):
            with self.assertRaises(GitReadError) as ctx:
                gitio.remove_worktree("/repo", "/repo/.worktrees/x")
        self.assertIn("timed out", str(ctx.exception))

    def test_an_absent_unregistered_path_is_success(self):
        with self._run(_proc(128, stderr="fatal: 'p' is not a working tree")):
            gitio.remove_worktree("/repo", "/nonexistent/path/for/test")

    def test_an_existing_unregistered_path_raises(self):
        with tempfile.TemporaryDirectory() as leftover:
            with self._run(_proc(128, stderr="fatal: 'p' is not a working tree")):
                with self.assertRaises(GitReadError):
                    gitio.remove_worktree("/repo", leftover)

    def test_prune_failure_raises(self):
        def side_effect(args, **kwargs):
            return _proc(1, stderr="prune boom") if "prune" in args else _proc(0)

        with patch("lightcycle.adapters.gitio.subprocess.run", side_effect=side_effect):
            with self.assertRaises(GitReadError) as ctx:
                gitio.remove_worktree("/repo", "/repo/.worktrees/x")
        self.assertIn("prune boom", str(ctx.exception))


class TestDeleteBranch(unittest.TestCase):
    def _run(self, exists, delete_proc):
        def side_effect(args, **kwargs):
            if "rev-parse" in args and "--git-dir" in args:
                return _proc(0)
            if "rev-parse" in args:
                return _proc(0 if exists else 1)
            return delete_proc

        return patch("lightcycle.adapters.gitio.subprocess.run", side_effect=side_effect)

    def test_raises_when_branch_delete_fails_for_an_existing_branch(self):
        with self._run(True, _proc(1, stderr="error: cannot delete branch 'b' used by worktree")):
            with self.assertRaises(GitReadError) as ctx:
                gitio.delete_branch("/repo", "b")
        self.assertIn("used by worktree", str(ctx.exception))

    def test_does_not_run_branch_delete_for_a_missing_branch(self):
        with self._run(False, _proc(1, stderr="should not run")) as mock_run:
            gitio.delete_branch("/repo", "b")
        self.assertFalse([c for c in mock_run.call_args_list if "-D" in c.args[0]])


class TestCloneIdentity(unittest.TestCase):
    def test_invokes_gh_repo_clone_and_returns_true_on_success(self):
        dest = tempfile.mkdtemp() + "/widget"
        with patch(
            "lightcycle.adapters.gitio.subprocess.run", return_value=_proc(0)
        ) as mock_run:
            result = GitAdapter().clone_identity("acme/widget", dest)
            self.assertTrue(result)
            mock_run.assert_called_once_with(
                ["gh", "repo", "clone", "acme/widget", dest],
                capture_output=True, text=True, timeout=gitio._GIT_TIMEOUT_SECONDS,
            )

    def test_returns_false_on_a_nonzero_returncode(self):
        dest = tempfile.mkdtemp() + "/widget"
        with patch("lightcycle.adapters.gitio.subprocess.run", return_value=_proc(1)):
            result = GitAdapter().clone_identity("acme/widget", dest)
            self.assertFalse(result)


class TestGitTimeoutFailsClosed(unittest.TestCase):
    def _timeout(self):
        return subprocess.TimeoutExpired(cmd=["git"], timeout=gitio._GIT_TIMEOUT_SECONDS)

    def test_timeout_yields_completed_process_with_nonzero_returncode(self):
        with patch("lightcycle.adapters.gitio.subprocess.run", side_effect=self._timeout()):
            proc = gitio.git("/repo", "rev-parse", "--git-dir")

        self.assertNotEqual(proc.returncode, 0)

    def test_is_git_repo_reads_timeout_as_not_a_repo_with_no_exception(self):
        with patch("lightcycle.adapters.gitio.subprocess.run", side_effect=self._timeout()):
            result = gitio.is_git_repo("/repo")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
