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
                ["open", "/specs/x.md"], capture_output=True, check=False
            )

    def test_uses_xdg_open_elsewhere(self):
        with patch("lightcycle.adapters.launcher.sys.platform", "linux"), patch(
            "lightcycle.adapters.launcher.subprocess.run", return_value=MagicMock(returncode=0)
        ) as mock_run:
            self.assertTrue(LauncherAdapter().open_path("/specs/x.md"))
            mock_run.assert_called_once_with(
                ["xdg-open", "/specs/x.md"], capture_output=True, check=False
            )

    def test_returns_false_on_a_nonzero_returncode(self):
        with patch(
            "lightcycle.adapters.launcher.subprocess.run", return_value=MagicMock(returncode=1)
        ):
            self.assertFalse(LauncherAdapter().open_path("/specs/x.md"))

    def test_returns_false_when_the_opener_is_not_installed(self):
        with patch("lightcycle.adapters.launcher.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(LauncherAdapter().open_path("/specs/x.md"))


if __name__ == "__main__":
    unittest.main()
