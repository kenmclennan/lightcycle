import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from lightcycle.adapters import gitio
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.ports.git import GitReadError


def _proc(returncode=0, stdout="", stderr=""):
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


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
            gitio.delete_remote_branch("/repo", "feat/auto-deleted")


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
