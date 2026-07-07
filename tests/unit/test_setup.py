import unittest

from lightcycle.application.setup import InitGridUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


class FakeConfig:
    def __init__(self, created=True):
        self._created = created

    def ensure_config(self):
        return self._created

    def config_path(self):
        return "/cfg/lightcycle/config"


class TestInitGrid(unittest.TestCase):
    def test_reports_existed_created_and_path(self):
        r = InitGridUseCase(FakeStore(), FakeFs(), FakeConfig(created=True)).execute()
        self.assertTrue(r.existed)
        self.assertTrue(r.created)
        self.assertEqual(r.config_path, "/cfg/lightcycle/config")

    def test_created_false_when_config_present(self):
        r = InitGridUseCase(FakeStore(), FakeFs(), FakeConfig(created=False)).execute()
        self.assertFalse(r.created)


if __name__ == "__main__":
    unittest.main()
