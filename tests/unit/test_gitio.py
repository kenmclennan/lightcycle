import unittest
from unittest.mock import MagicMock, patch

from the_grid.adapters import gitio


def _proc(returncode=0):
    return MagicMock(returncode=returncode, stdout="", stderr="")


class TestDeleteRemoteBranch(unittest.TestCase):
    def test_no_push_when_remote_branch_absent(self):
        with patch("the_grid.adapters.gitio.subprocess.run", return_value=_proc(1)) as mock_run:
            gitio.delete_remote_branch("/repo", "feat/gone")
            push_calls = [c for c in mock_run.call_args_list if "push" in c.args[0]]
            self.assertEqual(push_calls, [])

    def test_pushes_delete_when_remote_branch_present(self):
        with patch("the_grid.adapters.gitio.subprocess.run",
                   side_effect=[_proc(0), _proc(0)]) as mock_run:
            gitio.delete_remote_branch("/repo", "feat/present")
            push_calls = [c for c in mock_run.call_args_list if "push" in c.args[0]]
            self.assertEqual(len(push_calls), 1)
            self.assertIn("--delete", push_calls[0].args[0])
            self.assertIn("feat/present", push_calls[0].args[0])

    def test_tolerates_push_failure_when_remote_already_gone(self):
        with patch("the_grid.adapters.gitio.subprocess.run",
                   side_effect=[_proc(0), _proc(1)]):
            gitio.delete_remote_branch("/repo", "feat/auto-deleted")


if __name__ == "__main__":
    unittest.main()
