import unittest
from unittest.mock import MagicMock, patch

from lightcycle.adapters import gitio


def _proc(returncode=0):
    return MagicMock(returncode=returncode, stdout="", stderr="")


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


if __name__ == "__main__":
    unittest.main()
