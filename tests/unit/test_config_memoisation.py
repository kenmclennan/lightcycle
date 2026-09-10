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
            f.write("shortcode: LC\nmax-agents: 3\n")
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
            f.write("shortcode: LC\nmax-agents: 99\n")
        self.assertEqual(self.config.max_agents(), first)

    def test_reload_picks_up_an_edit(self):
        self.config.max_agents()
        with open(self.path, "w") as f:
            f.write("shortcode: LC\nmax-agents: 99\n")
        self.config.reload()
        self.assertEqual(self.config.max_agents(), 99)

    def test_writing_the_config_invalidates_the_cache(self):
        self.config.load_config()
        self.config.set_personal_origin("mine")
        self.assertEqual(self.config.load_config().get("personal-origin"), "mine")
