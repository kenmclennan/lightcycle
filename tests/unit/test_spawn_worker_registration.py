import tempfile
import unittest
from unittest import mock

from lightcycle.adapters import spawner
from lightcycle.adapters.workers import workers_state
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


if __name__ == "__main__":
    unittest.main()
