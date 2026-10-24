import unittest

from lightcycle.container import Container
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from tests.support.fake_store import FakeStore


class _Config:
    def context_artifact_project(self):
        return "specs"


class TestRegisteredSeedPaths(unittest.TestCase):
    def _container(self, store):
        return Container(
            config=_Config(), git=object(), store=store, spawner=object(), workers=object(),
            fs=object(), github=object(), lock=object(), breaker=object(),
        )

    def test_registered_guidance_and_specs_paths_are_returned(self):
        store = FakeStore()
        store.add_project(GUIDANCE_WORKSPACE, local_path="/elsewhere/guidance")
        store.add_project("specs", local_path="/elsewhere/specs")
        self.assertEqual(
            self._container(store).registered_seed_paths(),
            {"guidance-path": "/elsewhere/guidance", "specs-path": "/elsewhere/specs"},
        )

    def test_nothing_registered_returns_nothing(self):
        self.assertEqual(self._container(FakeStore()).registered_seed_paths(), {})
