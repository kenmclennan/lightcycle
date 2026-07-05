import unittest

from the_grid.application.errors import UseCaseError
from the_grid.application.work import OpenEpicInput, OpenEpicUseCase
from tests.support.fake_store import FakeStore


class TestOpenEpic(unittest.TestCase):
    def test_creates_epic_and_returns_its_id(self):
        s = FakeStore()
        resp = OpenEpicUseCase(s).execute(OpenEpicInput(objective="ship the thing"))
        self.assertEqual(s.get_task(resp.epic).type, "epic")
        self.assertEqual(s.get_task(resp.epic).title, "ship the thing")

    def test_links_backlog_when_given(self):
        s = FakeStore()
        backlog = s.create_task("a backlog item", role="human")
        resp = OpenEpicUseCase(s).execute(
            OpenEpicInput(objective="ship the thing", backlog=backlog)
        )
        arts = s.story_artifacts(resp.epic)
        self.assertEqual([(a.type, a.value) for a in arts], [("backlog", backlog)])

    def test_no_backlog_link_when_omitted(self):
        s = FakeStore()
        resp = OpenEpicUseCase(s).execute(OpenEpicInput(objective="ship the thing"))
        self.assertEqual(s.story_artifacts(resp.epic), [])

    def test_unknown_backlog_raises(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError):
            OpenEpicUseCase(s).execute(
                OpenEpicInput(objective="ship the thing", backlog="does-not-exist")
            )


if __name__ == "__main__":
    unittest.main()
