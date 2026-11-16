import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from lightcycle.adapters.process_group import run_in_group

_SPAWN_SLEEPER = ["sh", "-c", "sleep 300 & echo $! > %s; wait"]
_BOUNDED_POLL_SECONDS = 15.0


def _read_pid(path):
    deadline = time.monotonic() + _BOUNDED_POLL_SECONDS
    while time.monotonic() < deadline:
        try:
            with open(path) as f:
                text = f.read().strip()
            if text:
                return int(text)
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    return None


def _gone(pid):
    deadline = time.monotonic() + _BOUNDED_POLL_SECONDS
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _cleanup(pid):
    if pid is None:
        return
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        pass


class TestRunInGroup(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pidfile = os.path.join(self.dir, "pid")
        self.argv = [_SPAWN_SLEEPER[0], _SPAWN_SLEEPER[1], _SPAWN_SLEEPER[2] % self.pidfile]
        self.pid = None

    def tearDown(self):
        _cleanup(self.pid)

    def test_a_timeout_kills_the_grandchild(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_in_group(self.argv, timeout=2, capture_output=True)

        self.pid = _read_pid(self.pidfile)
        self.assertIsNotNone(self.pid)
        self.assertTrue(_gone(self.pid))

    def test_success_returns_a_completed_process(self):
        result = run_in_group(["sh", "-c", "echo hello"], timeout=10, capture_output=True, text=True)

        self.assertEqual((result.returncode, result.stdout), (0, "hello\n"))

    def test_check_raises_on_non_zero_exit(self):
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            run_in_group(["sh", "-c", "exit 3"], timeout=10, check=True)

        self.assertEqual(caught.exception.returncode, 3)

    def test_an_interrupt_kills_the_group(self):
        real = subprocess.Popen.communicate
        calls = []

        def interrupted(proc, *args, **kwargs):
            if not calls:
                calls.append(1)
                self.pid = _read_pid(self.pidfile)
                raise KeyboardInterrupt
            return real(proc, *args, **kwargs)

        with mock.patch.object(subprocess.Popen, "communicate", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                run_in_group(self.argv, timeout=30, capture_output=True)

        self.assertIsNotNone(self.pid)
        self.assertTrue(_gone(self.pid))


if __name__ == "__main__":
    unittest.main()
