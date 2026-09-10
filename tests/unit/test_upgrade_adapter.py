import subprocess
import unittest
import urllib.error
from unittest.mock import patch

from lightcycle.adapters.upgrade import UpgradeAdapter
from lightcycle.application.setup.upgrade import (
    ProcessListUnreadableError,
    RemoteVersionUnavailableError,
)


class FakeConfig:
    def base_env(self):
        return {}


def _adapter():
    return UpgradeAdapter(FakeConfig())


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


if __name__ == "__main__":
    unittest.main()
