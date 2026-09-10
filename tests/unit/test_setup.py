import unittest

from lightcycle.application.setup import InitGridUseCase
from lightcycle.domain.flow.flow import SPECS_WORKSPACE
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


class FakeConfig:
    def __init__(self, created=True, legacy=None):
        self._created = created
        self._legacy = legacy or {}

    def ensure_config(self):
        return self._created

    def config_path(self):
        return "/cfg/lightcycle/config"

    def load_config(self):
        return self._legacy

    def expand_path(self, v):
        return v


class TestInitGrid(unittest.TestCase):
    def test_reports_existed_created_and_path(self):
        r = InitGridUseCase(FakeStore(), FakeFs(), FakeConfig(created=True)).execute()
        self.assertTrue(r.existed)
        self.assertTrue(r.created)
        self.assertEqual(r.config_path, "/cfg/lightcycle/config")

    def test_created_false_when_config_present(self):
        r = InitGridUseCase(FakeStore(), FakeFs(), FakeConfig(created=False)).execute()
        self.assertFalse(r.created)

    def test_registers_a_default_specs_project_when_none_is_registered(self):
        store = FakeStore()
        InitGridUseCase(store, FakeFs(), FakeConfig()).execute()
        project = store.get_project(SPECS_WORKSPACE)
        self.assertEqual(project.local_path, "~/workspace/specs")
        self.assertIsNone(project.remote)

    def test_migrates_a_legacy_specs_config_into_the_project_registry(self):
        store = FakeStore()
        config = FakeConfig(legacy={"specs": "/old/specs", "specs-remote": "git@x:specs.git"})
        InitGridUseCase(store, FakeFs(), config).execute()
        project = store.get_project(SPECS_WORKSPACE)
        self.assertEqual(project.local_path, "/old/specs")
        self.assertEqual(project.remote, "git@x:specs.git")

    def test_leaves_an_already_registered_specs_project_untouched(self):
        store = FakeStore()
        store.add_project(SPECS_WORKSPACE, local_path="/existing", remote="git@x:existing.git")
        InitGridUseCase(store, FakeFs(), FakeConfig()).execute()
        project = store.get_project(SPECS_WORKSPACE)
        self.assertEqual(project.local_path, "/existing")
        self.assertEqual(project.remote, "git@x:existing.git")


if __name__ == "__main__":
    unittest.main()
