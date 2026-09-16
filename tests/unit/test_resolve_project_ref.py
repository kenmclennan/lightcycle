import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.resolve_project_ref import resolve_project_ref
from tests.support.fake_store import FakeStore


class TestResolveProjectRef(unittest.TestCase):
    def test_none_ref_returns_none(self):
        self.assertIsNone(resolve_project_ref(FakeStore(), None))

    def test_unregistered_ref_raises_naming_the_ref(self):
        store = FakeStore()
        with self.assertRaises(UseCaseError) as ctx:
            resolve_project_ref(store, "ghost")
        self.assertIn("ghost", str(ctx.exception))

    def test_ambiguous_ref_raises_naming_the_ref(self):
        store = FakeStore()
        store.add_project("acme/app", shortcode="ACME")
        store.add_project("other/app", shortcode="OTHER")
        with self.assertRaises(UseCaseError) as ctx:
            resolve_project_ref(store, "app")
        self.assertIn("app", str(ctx.exception))

    def test_full_identity_ref_returns_the_registered_short_name(self):
        store = FakeStore()
        store.add_project("acme/horde", shortcode="HORDE")
        self.assertEqual(resolve_project_ref(store, "acme/horde"), "horde")

    def test_short_name_ref_returns_itself(self):
        store = FakeStore()
        store.add_project("acme/horde", shortcode="HORDE")
        self.assertEqual(resolve_project_ref(store, "horde"), "horde")


if __name__ == "__main__":
    unittest.main()
