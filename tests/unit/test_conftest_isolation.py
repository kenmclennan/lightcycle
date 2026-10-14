import os
import unittest

from tests.conftest import _fresh_test_home


class TestIsolationStripsWorkerEnv(unittest.TestCase):
    def test_fresh_test_home_removes_worker_context(self):
        os.environ["LC_WORKER"] = "1"
        os.environ["LC_SPAWNID"] = "abc123"
        os.environ["LC_ROLE"] = "coder"
        _fresh_test_home()
        self.assertIsNone(os.environ.get("LC_WORKER"))
        self.assertIsNone(os.environ.get("LC_SPAWNID"))
        self.assertIsNone(os.environ.get("LC_ROLE"))


class TestIsolationFreshensUserHome(unittest.TestCase):
    def test_fresh_test_home_replaces_home_each_call(self):
        _fresh_test_home()
        first = os.environ["HOME"]
        _fresh_test_home()
        self.assertNotEqual(first, os.environ["HOME"])
        self.assertNotEqual(os.environ["HOME"], os.environ["LC_TEST_REAL_HOME"])


if __name__ == "__main__":
    unittest.main()
