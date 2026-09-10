import unittest

from lightcycle.application.setup import ProjectRegistry
from lightcycle.ports.store import ProjectResolutionError
from tests.support.fake_store import FakeStore


class TestProjectRegistry(unittest.TestCase):
    def test_resolve_path_passes_through_an_absolute_ref_without_a_lookup(self):
        s = FakeStore()
        self.assertEqual(ProjectRegistry(s).resolve_path("/elsewhere/app"), "/elsewhere/app")

    def test_resolve_path_matches_the_exact_owner_slash_name_identity(self):
        s = FakeStore()
        s.add_project("acme/horde", local_path="/p/horde")
        self.assertEqual(ProjectRegistry(s).resolve_path("acme/horde"), "/p/horde")

    def test_resolve_path_matches_an_unambiguous_bare_name(self):
        s = FakeStore()
        s.add_project("acme/horde", local_path="/p/horde")
        self.assertEqual(ProjectRegistry(s).resolve_path("horde"), "/p/horde")

    def test_resolve_path_raises_on_an_unregistered_ref(self):
        s = FakeStore()
        with self.assertRaises(ProjectResolutionError):
            ProjectRegistry(s).resolve_path("ghost")

    def test_resolve_path_raises_on_an_ambiguous_bare_name(self):
        s = FakeStore()
        s.add_project("acme/app", local_path="/p/acme-app")
        s.add_project("other/app", local_path="/p/other-app")
        with self.assertRaises(ProjectResolutionError):
            ProjectRegistry(s).resolve_path("app")

    def test_resolve_path_raises_when_registered_without_a_local_checkout(self):
        s = FakeStore()
        s.add_project("acme/horde", shortcode="HORDE")
        with self.assertRaises(ProjectResolutionError) as ctx:
            ProjectRegistry(s).resolve_path("horde")
        self.assertIn("activate the item to clone it automatically", str(ctx.exception))

    def test_find_matches_the_exact_owner_slash_name_identity(self):
        s = FakeStore()
        s.add_project("acme/horde", local_path="/p/horde")
        self.assertEqual(ProjectRegistry(s).find("acme/horde").identity, "acme/horde")

    def test_find_matches_an_unambiguous_bare_name(self):
        s = FakeStore()
        s.add_project("acme/horde", local_path="/p/horde")
        self.assertEqual(ProjectRegistry(s).find("horde").identity, "acme/horde")

    def test_find_raises_on_an_unregistered_ref(self):
        s = FakeStore()
        with self.assertRaises(ProjectResolutionError):
            ProjectRegistry(s).find("ghost")

    def test_find_raises_on_an_ambiguous_bare_name(self):
        s = FakeStore()
        s.add_project("acme/app", local_path="/p/acme-app")
        s.add_project("other/app", local_path="/p/other-app")
        with self.assertRaises(ProjectResolutionError):
            ProjectRegistry(s).find("app")

    def test_find_returns_the_entry_with_a_null_local_path_without_raising(self):
        s = FakeStore()
        s.add_project("acme/horde", shortcode="HORDE")
        project = ProjectRegistry(s).find("horde")
        self.assertEqual(project.identity, "acme/horde")
        self.assertIsNone(project.local_path)


if __name__ == "__main__":
    unittest.main()
