import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work import OpenThemeInput, OpenThemeUseCase
from tests.support.fake_store import FakeStore


class FakeConfig:
    def __init__(self, shortcode="XY"):
        self._shortcode = shortcode

    def shortcode(self):
        return self._shortcode


class TestOpenEpic(unittest.TestCase):
    def test_creates_epic_and_returns_its_id(self):
        s = FakeStore()
        resp = OpenThemeUseCase(s, FakeConfig()).execute(OpenThemeInput(objective="ship the thing"))
        self.assertEqual(s.get_node(resp.theme).type, "theme")
        self.assertEqual(s.get_node(resp.theme).title, "ship the thing")

    def test_links_backlog_when_given(self):
        s = FakeStore()
        backlog = s.create_step("a backlog item", role="human")
        resp = OpenThemeUseCase(s, FakeConfig()).execute(
            OpenThemeInput(objective="ship the thing", backlog=[backlog])
        )
        arts = s.item_artifacts(resp.theme)
        self.assertEqual([(a.type, a.value) for a in arts], [("resolves", backlog)])

    def test_links_multiple_backlog_ids_when_given(self):
        s = FakeStore()
        b1 = s.create_step("a backlog item", role="human")
        b2 = s.create_step("another backlog item", role="human")
        resp = OpenThemeUseCase(s, FakeConfig()).execute(
            OpenThemeInput(objective="ship the thing", backlog=[b1, b2])
        )
        arts = s.item_artifacts(resp.theme)
        self.assertEqual([(a.type, a.value) for a in arts], [("resolves", b1), ("resolves", b2)])

    def test_no_backlog_link_when_omitted(self):
        s = FakeStore()
        resp = OpenThemeUseCase(s, FakeConfig()).execute(OpenThemeInput(objective="ship the thing"))
        self.assertEqual(s.item_artifacts(resp.theme), [])

    def test_unknown_backlog_raises(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError):
            OpenThemeUseCase(s, FakeConfig()).execute(
                OpenThemeInput(objective="ship the thing", backlog=["does-not-exist"])
            )

    def test_attaches_repo_artifact_when_given(self):
        s = FakeStore()
        resp = OpenThemeUseCase(s, FakeConfig()).execute(
            OpenThemeInput(objective="ship the thing", repo="lightcycle")
        )
        arts = s.item_artifacts(resp.theme)
        self.assertEqual([(a.type, a.value) for a in arts], [("repo", "lightcycle")])

    def test_no_repo_artifact_when_omitted(self):
        s = FakeStore()
        resp = OpenThemeUseCase(s, FakeConfig()).execute(OpenThemeInput(objective="ship the thing"))
        self.assertEqual(s.item_artifacts(resp.theme), [])

    def test_no_project_defaults_to_the_global_shortcode(self):
        s = FakeStore()
        resp = OpenThemeUseCase(s, FakeConfig(shortcode="XY")).execute(
            OpenThemeInput(objective="ship the thing")
        )
        self.assertEqual(resp.shortcode, "XY")
        self.assertTrue(resp.shortcode_defaulted)

    def test_unregistered_project_raises_and_creates_nothing(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError):
            OpenThemeUseCase(s, FakeConfig()).execute(
                OpenThemeInput(objective="ship the thing", project="ghost/repo")
            )
        self.assertEqual(s.all_nodes(), [])

    def test_ambiguous_project_raises_and_creates_nothing(self):
        s = FakeStore()
        s.add_project("acme/app", shortcode="ACME")
        s.add_project("other/app", shortcode="OTHER")
        with self.assertRaises(UseCaseError):
            OpenThemeUseCase(s, FakeConfig()).execute(
                OpenThemeInput(objective="ship the thing", project="app")
            )
        self.assertEqual(s.all_nodes(), [])

    def test_project_with_no_shortcode_raises_and_creates_nothing(self):
        s = FakeStore()
        s.add_project("acme/ghost", local_path="/x")
        with self.assertRaises(UseCaseError):
            OpenThemeUseCase(s, FakeConfig()).execute(
                OpenThemeInput(objective="ship the thing", project="acme/ghost")
            )
        self.assertEqual(s.all_nodes(), [])


if __name__ == "__main__":
    unittest.main()
