import os
import tempfile
import unittest
from unittest import mock

from lightcycle.adapters import spawner
from lightcycle.adapters.workers import workers_path, workers_state
from lightcycle.config import Config


class FakeProc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


class TestSpawnWorkerRegistersBeforeCaptureResolves(unittest.TestCase):
    def test_registry_entry_exists_before_capture_pid_started_resolves(self):
        with tempfile.TemporaryDirectory() as root:
            config = Config(environ={"LC_HOME": root})
            seen = {}

            def never_resolving_capture(proc):
                seen["workers"] = workers_state(root)
                return None

            with mock.patch(
                "lightcycle.adapters.spawner.subprocess.Popen",
                return_value=FakeProc(pid=999),
            ), mock.patch(
                "lightcycle.adapters.spawner.capture_pid_started",
                side_effect=never_resolving_capture,
            ):
                result = spawner.spawn_worker(config, "agent")

            self.assertEqual(len(seen["workers"]), 1)
            self.assertEqual(seen["workers"][0]["pid"], 999)
            self.assertIsNone(seen["workers"][0]["pid_started"])
            self.assertEqual(seen["workers"][0]["spawnid"], result["spawnid"])


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class TestSpawnWorkerTerminatesOnUnreadableRegistry(unittest.TestCase):
    def test_kills_the_process_and_returns_none_when_registry_is_unreadable(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "logs"), exist_ok=True)
            with open(workers_path(root), "w") as f:
                f.write("{not valid json")
            config = Config(environ={"LC_HOME": root, "LC_SPAWN_CMD": "exec sleep 30"})
            spawned = {}
            real_popen = spawner.subprocess.Popen

            def recording_popen(*args, **kwargs):
                proc = real_popen(*args, **kwargs)
                spawned["proc"] = proc
                return proc

            with mock.patch(
                "lightcycle.adapters.spawner.subprocess.Popen", side_effect=recording_popen
            ):
                result = spawner.spawn_worker(config, "agent")

            self.assertIsNone(result)
            self.assertIn("proc", spawned)
            rc = spawned["proc"].wait(timeout=3)
            self.assertIsNotNone(rc)
            self.assertFalse(_pid_alive(spawned["proc"].pid))


if __name__ == "__main__":
    unittest.main()
