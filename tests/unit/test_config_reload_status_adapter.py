import json
import os
import tempfile
import unittest

from lightcycle.adapters.config_reload_status import ConfigReloadStatusAdapter
from lightcycle.domain.pool import ConfigReloadState


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def data_root(self):
        return self._root


class TestConfigReloadStatusAdapter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.path = os.path.join(self.root, "logs", "config_reload.json")
        self.status = ConfigReloadStatusAdapter(FakeConfig(self.root))

    def _write(self, text):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write(text)

    def test_load_with_no_state_file_is_none(self):
        self.assertIsNone(self.status.load())

    def test_save_then_load_round_trips_through_logs_config_reload_json(self):
        state = ConfigReloadState(
            pid=7, outcome="rejected", reason="bad", rejected_mtime=12,
            restart_required=("poll-seconds",))
        self.status.save(state)
        self.assertEqual(self.status.load(), state)
        self.assertTrue(os.path.exists(self.path))

    def test_the_file_carries_the_key_set_written_before_the_named_type(self):
        self.status.save(ConfigReloadState(pid=7, outcome="reloaded"))
        with open(self.path) as f:
            data = json.load(f)
        self.assertEqual(
            set(data), {"pid", "outcome", "reason", "rejected_mtime", "restart_required"})
        self.assertEqual(data["restart_required"], [])

    def test_invalid_json_loads_as_none(self):
        self._write("{not json")
        self.assertIsNone(self.status.load())

    def test_a_json_list_loads_as_none(self):
        self._write("[1, 2]")
        self.assertIsNone(self.status.load())


if __name__ == "__main__":
    unittest.main()
