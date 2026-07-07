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
            OpenThemeInput(objective="ship the thing", backlog=backlog)
        )
        arts = s.item_artifacts(resp.theme)
        self.assertEqual([(a.type, a.value) for a in arts], [("backlog", backlog)])

    def test_no_backlog_link_when_omitted(self):
        s = FakeStore()
        resp = OpenThemeUseCase(s).execute(OpenThemeInput(objective="ship the thing"))
        self.assertEqual(s.item_artifacts(resp.theme), [])

    def test_unknown_backlog_raises(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError):
            OpenThemeUseCase(s).execute(
                OpenThemeInput(objective="ship the thing", backlog="does-not-exist")
            )


if __name__ == "__main__":
    unittest.main()
