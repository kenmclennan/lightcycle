import os
import tempfile
import unittest
from unittest import mock

from lightcycle.adapters import spawner
from lightcycle.adapters.workers import workers_path
from lightcycle.config import Config


class FakeProc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None

    def terminate(self):
        pass


class TestSpawnWorkerScratch(unittest.TestCase):
    def _spawn(self, environ):
        with mock.patch(
            "lightcycle.adapters.spawner.subprocess.Popen", return_value=FakeProc(999)
        ) as popen, mock.patch(
            "lightcycle.adapters.spawner.capture_pid_started", return_value=1.0
        ):
            result = spawner.spawn_worker(Config(environ=environ), "agent")
        return result, popen.call_args.kwargs["env"]

    def test_worker_env_has_tmpdir_under_scratch_for_default_and_override_branch(self):
        for extra in ({}, {"LC_SPAWN_CMD": "exit 0"}):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as root:
                result, env = self._spawn(dict({"LC_HOME": root, "LC_MAX_AGENTS": "5"}, **extra))
                expected = os.path.join(root, "scratch", result["spawnid"])
                self.assertEqual(env["TMPDIR"], expected)
                self.assertEqual(os.stat(expected).st_mode & 0o777, 0o700)

    def test_unreadable_registry_removes_the_folder(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "logs"))
            with open(workers_path(root), "w") as f:
                f.write("{not valid json")
            with mock.patch(
                "lightcycle.adapters.spawner.subprocess.Popen", return_value=FakeProc(999)
            ):
                result = spawner.spawn_worker(
                    Config(environ={"LC_HOME": root, "LC_MAX_AGENTS": "5"}), "agent"
                )
            self.assertIsNone(result)
            self.assertEqual(os.listdir(os.path.join(root, "scratch")), [])


if __name__ == "__main__":
    unittest.main()
