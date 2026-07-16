import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work import OpenThemeInput, OpenThemeUseCase
from tests.support.fake_store import FakeStore


class TestOpenEpic(unittest.TestCase):
    def test_creates_epic_and_returns_its_id(self):
        s = FakeStore()
        resp = OpenThemeUseCase(s).execute(OpenThemeInput(objective="ship the thing"))
        self.assertEqual(s.get_node(resp.theme).type, "theme")
        self.assertEqual(s.get_node(resp.theme).title, "ship the thing")

    def test_links_backlog_when_given(self):
        s = FakeStore()
        backlog = s.create_step("a backlog item", role="human")
        resp = OpenThemeUseCase(s).execute(
            OpenThemeInput(objective="ship the thing", backlog=[backlog])
        )
        arts = s.item_artifacts(resp.theme)
        self.assertEqual([(a.type, a.value) for a in arts], [("resolves", backlog)])

    def test_links_multiple_backlog_ids_when_given(self):
        s = FakeStore()
        b1 = s.create_step("a backlog item", role="human")
        b2 = s.create_step("another backlog item", role="human")
        resp = OpenThemeUseCase(s).execute(
            OpenThemeInput(objective="ship the thing", backlog=[b1, b2])
        )
        arts = s.item_artifacts(resp.theme)
        self.assertEqual([(a.type, a.value) for a in arts], [("resolves", b1), ("resolves", b2)])

    def test_no_backlog_link_when_omitted(self):
        s = FakeStore()
        resp = OpenThemeUseCase(s).execute(OpenThemeInput(objective="ship the thing"))
        self.assertEqual(s.item_artifacts(resp.theme), [])

    def test_unknown_backlog_raises(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError):
            OpenThemeUseCase(s).execute(
                OpenThemeInput(objective="ship the thing", backlog=["does-not-exist"])
            )

    def test_attaches_repo_artifact_when_given(self):
        s = FakeStore()
        resp = OpenThemeUseCase(s).execute(
            OpenThemeInput(objective="ship the thing", repo="lightcycle")
        )
        arts = s.item_artifacts(resp.theme)
        self.assertEqual([(a.type, a.value) for a in arts], [("repo", "lightcycle")])

    def test_no_repo_artifact_when_omitted(self):
        s = FakeStore()
        resp = OpenThemeUseCase(s).execute(OpenThemeInput(objective="ship the thing"))
        self.assertEqual(s.item_artifacts(resp.theme), [])


if __name__ == "__main__":
    unittest.main()
