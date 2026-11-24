import subprocess
import unittest
from unittest import mock

from lightcycle.adapters import workers as wk


def _counting_run_in_group(counter):
    real = wk.run_in_group

    def run(*args, **kwargs):
        counter.append(args)
        return real(*args, **kwargs)

    return run


class TestWorkerAliveSkipsPs(unittest.TestCase):
    def test_dead_pid_runs_no_subprocess(self):
        child = subprocess.Popen(["true"])
        child.wait()
        calls = []

        with mock.patch.object(wk, "run_in_group", _counting_run_in_group(calls)):
            alive = wk.worker_alive(child.pid, "x")

        self.assertFalse(alive)
        self.assertEqual(len(calls), 0)

    def test_live_pid_runs_one_subprocess(self):
        child = subprocess.Popen(["sleep", "30"])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        calls = []

        with mock.patch.object(wk, "run_in_group", _counting_run_in_group(calls)):
            alive = wk.worker_alive(child.pid, None)

        self.assertTrue(alive)
        self.assertEqual(len(calls), 1)
