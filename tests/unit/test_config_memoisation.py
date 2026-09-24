import os
import tempfile
import unittest
from unittest.mock import patch

from lightcycle.config import Config


class TestConfigIsReadOnce(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.path = os.path.join(self.home, "config")
        with open(self.path, "w") as f:
            f.write("max-agents: 3\n")
        self.config = Config(environ={"LC_HOME": self.home, "LC_CONFIG": self.path})

    def test_many_getters_parse_the_file_once(self):
        with patch.object(Config, "_read_config", wraps=self.config._read_config) as reads:
            for _ in range(5):
                self.config.load_config()
                self.config.max_agents()
            self.assertEqual(reads.call_count, 1)

    def test_a_mid_run_edit_is_not_picked_up_half_way(self):
        first = self.config.max_agents()
        with open(self.path, "w") as f:
            f.write("max-agents: 99\n")
        self.assertEqual(self.config.max_agents(), first)

    def test_reload_picks_up_an_edit(self):
        self.config.max_agents()
        with open(self.path, "w") as f:
            f.write("max-agents: 99\n")
        self.config.reload()
        self.assertEqual(self.config.max_agents(), 99)

    def test_writing_the_config_invalidates_the_cache(self):
        self.config.load_config()
        self.config.set_personal_origin("mine")
        self.assertEqual(self.config.load_config().get("personal-origin"), "mine")

    def test_config_mtime_moves_when_the_file_is_edited(self):
        before = self.config.config_mtime()
        os.utime(self.path, ns=(before + 1_000_000_000, before + 1_000_000_000))
        self.assertNotEqual(self.config.config_mtime(), before)

    def test_config_mtime_is_none_when_the_file_is_absent(self):
        os.remove(self.path)
        self.assertIsNone(self.config.config_mtime())
