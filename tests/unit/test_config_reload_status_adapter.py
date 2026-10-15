import os
import tempfile
import unittest

from lightcycle.adapters.config_reload_status import ConfigReloadStatusAdapter


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def data_root(self):
        return self._root


class TestConfigReloadStatusAdapter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.status = ConfigReloadStatusAdapter(FakeConfig(self.root))

    def test_load_with_no_state_file_is_empty(self):
        self.assertEqual(self.status.load(), {})

    def test_save_then_load_round_trips_through_logs_config_reload_json(self):
        state = {"pid": 7, "outcome": "rejected", "restart_required": ["poll-seconds"]}
        self.status.save(state)
        self.assertEqual(self.status.load(), state)
        self.assertTrue(os.path.exists(os.path.join(self.root, "logs", "config_reload.json")))


if __name__ == "__main__":
    unittest.main()
