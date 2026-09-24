import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.resolve_shortcode import ResolvedShortcode, resolve_shortcode
from tests.support.fake_store import FakeStore


class TestResolveShortcode(unittest.TestCase):
    def _refusal(self, store, project, repo=None):
        with self.assertRaises(UseCaseError) as ctx:
            resolve_shortcode(store, project, repo)
        return str(ctx.exception)

    def test_single_match_with_a_shortcode_returns_it(self):
        store = FakeStore()
        store.add_project("acme/horde", shortcode="HORDE")
        self.assertEqual(resolve_shortcode(store, "horde"), ResolvedShortcode("HORDE"))

    def test_zero_matches_raises_naming_the_ref(self):
        self.assertIn("ghost", self._refusal(FakeStore(), "ghost"))

    def test_ambiguous_match_raises(self):
        store = FakeStore()
        store.add_project("acme/app", shortcode="ACME")
        store.add_project("other/app", shortcode="OTHER")
        self.assertIn("ambiguous", self._refusal(store, "app"))

    def test_matched_project_with_no_shortcode_raises_naming_the_identity(self):
        store = FakeStore()
        store.add_project("acme/ghost", local_path="/x")
        message = self._refusal(store, "acme/ghost")
        self.assertIn("registered but has no shortcode", message)
        self.assertIn("lc project add acme/ghost --shortcode <PREFIX>", message)

    def test_no_project_but_registered_repo_derives_shortcode_and_project(self):
        store = FakeStore()
        store.add_project("kenmclennan/lightcycle", shortcode="LC")
        resolved = resolve_shortcode(store, None, repo="kenmclennan/lightcycle")
        self.assertEqual(resolved, ResolvedShortcode("LC", "lightcycle"))

    def test_no_project_and_repo_registered_with_no_shortcode_refuses_like_project_does(self):
        store = FakeStore()
        store.add_project("acme/ghost", local_path="/x")
        self.assertEqual(
            self._refusal(store, None, repo="acme/ghost"), self._refusal(store, "acme/ghost")
        )

    def test_no_project_and_unregistered_repo_refuses_naming_repo_and_both_fixes(self):
        message = self._refusal(FakeStore(), None, repo="ghost/repo")
        self.assertIn("ghost/repo", message)
        self.assertIn("lc project add ghost/repo --shortcode <PREFIX>", message)
        self.assertIn("--project", message)

    def test_no_project_and_ambiguous_repo_surfaces_the_registry_ambiguity(self):
        store = FakeStore()
        store.add_project("acme/app", shortcode="ACME")
        store.add_project("other/app", shortcode="OTHER")
        self.assertIn("ambiguous", self._refusal(store, None, repo="app"))

    def test_neither_project_nor_repo_refuses_naming_both_fixes(self):
        message = self._refusal(FakeStore(), None)
        self.assertIn("--project", message)
        self.assertIn("lc project add <repo> --shortcode <PREFIX>", message)
        self.assertIn("--repo", message)

    def test_project_wins_over_an_unresolvable_repo(self):
        store = FakeStore()
        store.add_project("acme/app", shortcode="ACME")
        resolved = resolve_shortcode(store, "acme/app", repo="ghost/repo")
        self.assertEqual(resolved, ResolvedShortcode("ACME"))


if __name__ == "__main__":
    unittest.main()
