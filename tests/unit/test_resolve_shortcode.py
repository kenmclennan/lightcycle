import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.resolve_shortcode import ResolvedShortcode, resolve_shortcode
from tests.support.fake_store import FakeStore


class FakeConfig:
    def __init__(self, shortcode="XY"):
        self._shortcode = shortcode

    def shortcode(self):
        return self._shortcode


class TestResolveShortcode(unittest.TestCase):
    def test_no_project_returns_the_defaulted_global_shortcode(self):
        resolved = resolve_shortcode(FakeStore(), FakeConfig(shortcode="XY"), None)
        self.assertEqual(resolved, ResolvedShortcode("XY", True))

    def test_single_match_with_a_shortcode_returns_it_not_defaulted(self):
        store = FakeStore()
        store.add_project("acme/horde", shortcode="HORDE")
        resolved = resolve_shortcode(store, FakeConfig(), "horde")
        self.assertEqual(resolved, ResolvedShortcode("HORDE", False))

    def test_zero_matches_raises_naming_the_ref(self):
        store = FakeStore()
        with self.assertRaises(UseCaseError) as ctx:
            resolve_shortcode(store, FakeConfig(), "ghost")
        self.assertIn("ghost", str(ctx.exception))

    def test_ambiguous_match_raises(self):
        store = FakeStore()
        store.add_project("acme/app", shortcode="ACME")
        store.add_project("other/app", shortcode="OTHER")
        with self.assertRaises(UseCaseError) as ctx:
            resolve_shortcode(store, FakeConfig(), "app")
        self.assertIn("app", str(ctx.exception))

    def test_matched_project_with_no_shortcode_raises_naming_the_identity(self):
        store = FakeStore()
        store.add_project("acme/ghost", local_path="/x")
        with self.assertRaises(UseCaseError) as ctx:
            resolve_shortcode(store, FakeConfig(), "acme/ghost")
        self.assertIn("acme/ghost", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
