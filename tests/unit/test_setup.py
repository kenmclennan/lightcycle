import unittest

from the_grid.application.setup import InitGrid
from tests.fake_fs import FakeFs
from tests.fake_store import FakeStore


class FakeConfig:
    def __init__(self, created=True):
        self._created = created

    def ensure_config(self):
        return self._created

    def config_path(self):
        return "/cfg/the-grid/config"


class TestInitGrid(unittest.TestCase):
    def test_reports_existed_created_and_path(self):
        r = InitGrid(FakeStore(), FakeFs(), FakeConfig(created=True)).execute()
        self.assertTrue(r["existed"])  # FakeFs.store_ready() is True
        self.assertTrue(r["created"])
        self.assertEqual(r["config_path"], "/cfg/the-grid/config")

    def test_created_false_when_config_present(self):
        r = InitGrid(FakeStore(), FakeFs(), FakeConfig(created=False)).execute()
        self.assertFalse(r["created"])


if __name__ == "__main__":
    unittest.main()
