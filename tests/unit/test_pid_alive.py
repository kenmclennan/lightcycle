import errno
import unittest
from unittest import mock

from lightcycle.adapters.workers import pid_alive


class TestPidAlive(unittest.TestCase):
    def test_permission_error_means_the_process_exists(self):
        with mock.patch("os.kill", side_effect=PermissionError(errno.EPERM, "denied")):
            self.assertTrue(pid_alive(4242))

    def test_no_such_process_means_dead(self):
        with mock.patch("os.kill", side_effect=ProcessLookupError(errno.ESRCH, "gone")):
            self.assertFalse(pid_alive(4242))

    def test_signal_zero_success_means_alive(self):
        with mock.patch("os.kill", return_value=None):
            self.assertTrue(pid_alive(4242))

    def test_unparseable_pid_means_dead(self):
        self.assertFalse(pid_alive("not-a-pid"))
        self.assertFalse(pid_alive(None))
