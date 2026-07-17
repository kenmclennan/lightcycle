import os
import tempfile
import unittest

from tests.support.fake_store import FakeStore
from tests.support.isolation import FrozenEnvironError, inject_container


class TestInjectContainerFrozenEnviron(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.config_path = os.path.join(self.home, "config")
        self.store = FakeStore()

    def test_mutating_os_environ_after_inject_raises(self):
        config = inject_container(
            self, store=self.store, home=self.home, config_path=self.config_path
        )
        os.environ["LC_WORKER"] = "1"
        self.addCleanup(os.environ.pop, "LC_WORKER", None)
        with self.assertRaises(FrozenEnvironError):
            config.is_worker()

    def test_extra_env_override_unaffected_by_later_mutation(self):
        config = inject_container(
            self, store=self.store, home=self.home, config_path=self.config_path,
            extra_env={"LC_SPAWNID": "spawn-xyz"},
        )
        os.environ["LC_SPAWNID"] = "spawn-abc"
        self.addCleanup(os.environ.pop, "LC_SPAWNID", None)
        self.assertEqual(config.spawn_id(), "spawn-xyz")

    def test_untouched_key_behaves_as_before(self):
        config = inject_container(
            self, store=self.store, home=self.home, config_path=self.config_path
        )
        self.assertIsNone(config.spawn_cmd())


if __name__ == "__main__":
    unittest.main()
