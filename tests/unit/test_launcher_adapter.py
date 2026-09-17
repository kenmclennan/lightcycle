import subprocess
import unittest
from unittest.mock import MagicMock, patch

from lightcycle.adapters.launcher import LauncherAdapter


class TestOpenUrl(unittest.TestCase):
    def test_returns_true_when_the_browser_opens_it(self):
        with patch("lightcycle.adapters.launcher.webbrowser.open", return_value=True) as mock_open:
            self.assertTrue(LauncherAdapter().open_url("https://gh/pr/1"))
            mock_open.assert_called_once_with("https://gh/pr/1")

    def test_returns_false_when_no_browser_is_available(self):
        with patch("lightcycle.adapters.launcher.webbrowser.open", return_value=False):
            self.assertFalse(LauncherAdapter().open_url("https://gh/pr/1"))

    def test_returns_false_when_opening_raises(self):
        with patch("lightcycle.adapters.launcher.webbrowser.open", side_effect=OSError):
            self.assertFalse(LauncherAdapter().open_url("https://gh/pr/1"))


class TestOpenPath(unittest.TestCase):
    def test_uses_open_on_macos(self):
        with patch("lightcycle.adapters.launcher.sys.platform", "darwin"), patch(
            "lightcycle.adapters.launcher.subprocess.run", return_value=MagicMock(returncode=0)
        ) as mock_run:
            self.assertTrue(LauncherAdapter().open_path("/specs/x.md"))
            mock_run.assert_called_once_with(
                ["open", "/specs/x.md"], capture_output=True, check=False, timeout=10
            )

    def test_uses_xdg_open_elsewhere(self):
        with patch("lightcycle.adapters.launcher.sys.platform", "linux"), patch(
            "lightcycle.adapters.launcher.subprocess.run", return_value=MagicMock(returncode=0)
        ) as mock_run:
            self.assertTrue(LauncherAdapter().open_path("/specs/x.md"))
            mock_run.assert_called_once_with(
                ["xdg-open", "/specs/x.md"], capture_output=True, check=False, timeout=10
            )

    def test_returns_false_on_a_nonzero_returncode(self):
        with patch(
            "lightcycle.adapters.launcher.subprocess.run", return_value=MagicMock(returncode=1)
        ):
            self.assertFalse(LauncherAdapter().open_path("/specs/x.md"))

    def test_returns_false_when_the_opener_is_not_installed(self):
        with patch("lightcycle.adapters.launcher.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(LauncherAdapter().open_path("/specs/x.md"))


class TestEdit(unittest.TestCase):
    def test_runs_the_editor_on_the_given_path_and_returns_its_exit_code(self):
        with patch(
            "lightcycle.adapters.launcher.subprocess.run", return_value=MagicMock(returncode=0)
        ) as mock_run:
            self.assertEqual(LauncherAdapter().edit("vi", "/x/config"), 0)
            mock_run.assert_called_once_with(["vi", "/x/config"], timeout=None)

    def test_propagates_a_nonzero_exit_code(self):
        with patch(
            "lightcycle.adapters.launcher.subprocess.run", return_value=MagicMock(returncode=1)
        ):
            self.assertEqual(LauncherAdapter().edit("vi", "/x/config"), 1)

    def test_does_not_catch_a_missing_editor(self):
        with patch("lightcycle.adapters.launcher.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                LauncherAdapter().edit("vi", "/x/config")

    def test_splits_an_editor_command_carrying_arguments(self):
        with patch(
            "lightcycle.adapters.launcher.subprocess.run", return_value=MagicMock(returncode=0)
        ) as mock_run:
            LauncherAdapter().edit("code --wait", "/x/config")
            mock_run.assert_called_once_with(["code", "--wait", "/x/config"], timeout=None)

    def test_preserves_a_quoted_path_with_a_space_in_the_editor_command(self):
        with patch(
            "lightcycle.adapters.launcher.subprocess.run", return_value=MagicMock(returncode=0)
        ) as mock_run:
            LauncherAdapter().edit('"/opt/my editor/bin/edit" --wait', "/x/config")
            mock_run.assert_called_once_with(
                ["/opt/my editor/bin/edit", "--wait", "/x/config"], timeout=None
            )


class TestEditDetached(unittest.TestCase):
    def test_launches_the_editor_without_waiting_for_it_to_exit(self):
        with patch("lightcycle.adapters.launcher.subprocess.Popen") as mock_popen:
            LauncherAdapter().edit_detached("vi", "/repo/.worktrees/x")
            mock_popen.assert_called_once_with(
                ["vi", "/repo/.worktrees/x"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            mock_popen.return_value.wait.assert_not_called()

    def test_does_not_catch_a_missing_editor(self):
        with patch("lightcycle.adapters.launcher.subprocess.Popen", side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                LauncherAdapter().edit_detached("vi", "/repo/.worktrees/x")

    def test_splits_an_editor_command_carrying_arguments(self):
        with patch("lightcycle.adapters.launcher.subprocess.Popen") as mock_popen:
            LauncherAdapter().edit_detached("code --wait", "/repo/.worktrees/x")
            mock_popen.assert_called_once_with(
                ["code", "--wait", "/repo/.worktrees/x"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    unittest.main()
