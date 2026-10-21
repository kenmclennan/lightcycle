import subprocess
import unittest
import urllib.error
from unittest.mock import patch

from lightcycle.adapters.upgrade import UpgradeAdapter, parse_remote_version
from lightcycle.ports.upgrade import (
    ProcessListUnreadableError,
    RemoteVersionUnavailableError,
    UpgradeInstallError,
)


class FakeConfig:
    def base_env(self):
        return {}


def _adapter():
    return UpgradeAdapter(FakeConfig())


class TestParseRemoteVersion(unittest.TestCase):
    def test_extracts_the_version_from_init_source(self):
        self.assertEqual(parse_remote_version('__version__ = "1.2.3"\n'), "1.2.3")

    def test_returns_none_when_no_version_line(self):
        self.assertIsNone(parse_remote_version("no version here\n"))


class TestListProcesses(unittest.TestCase):
    def test_raises_when_ps_cannot_be_run(self):
        with patch("lightcycle.adapters.upgrade.subprocess.run", side_effect=OSError("no such file")):
            with self.assertRaises(ProcessListUnreadableError):
                _adapter().list_processes()

    def test_raises_when_ps_exits_nonzero(self):
        result = subprocess.CompletedProcess(args=["ps"], returncode=1, stdout=b"")
        with patch("lightcycle.adapters.upgrade.subprocess.run", return_value=result):
            with self.assertRaises(ProcessListUnreadableError):
                _adapter().list_processes()

    def test_returns_decoded_output_when_ps_succeeds(self):
        result = subprocess.CompletedProcess(args=["ps"], returncode=0, stdout=b"123 command\n")
        with patch("lightcycle.adapters.upgrade.subprocess.run", return_value=result):
            self.assertEqual(_adapter().list_processes(), "123 command\n")


class TestFetchRemoteVersion(unittest.TestCase):
    def test_wraps_url_error_in_remote_version_unavailable_error(self):
        with patch("lightcycle.adapters.upgrade.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("unreachable")):
            with self.assertRaises(RemoteVersionUnavailableError):
                _adapter().fetch_remote_version()


class TestInstallUpgrade(unittest.TestCase):
    def test_translates_a_nonzero_exit_into_upgrade_install_error(self):
        failure = subprocess.CalledProcessError(2, ["pipx"])
        with patch("lightcycle.adapters.upgrade.subprocess.run", side_effect=failure):
            with self.assertRaisesRegex(UpgradeInstallError, "status 2"):
                _adapter().install_upgrade()

    def test_translates_a_timeout_into_upgrade_install_error(self):
        failure = subprocess.TimeoutExpired(["pipx"], 300)
        with patch("lightcycle.adapters.upgrade.subprocess.run", side_effect=failure):
            with self.assertRaisesRegex(UpgradeInstallError, "300 seconds"):
                _adapter().install_upgrade()


if __name__ == "__main__":
    unittest.main()
