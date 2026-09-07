import unittest

from lightcycle.application.work.item_filter import project_matches, text_matches
from tests.support.fake_store import FakeStore


class TestProjectMatches(unittest.TestCase):
    def test_none_short_ref_matches_everything(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertTrue(project_matches(s, s.get_item(item), None))

    def test_matches_the_bare_last_segment_of_the_repo(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.add_artifact(item, "repo", "kenmclennan/lightcycle")
        self.assertTrue(project_matches(s, s.get_item(item), "lightcycle"))

    def test_does_not_match_a_different_project(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.add_artifact(item, "repo", "kenmclennan/lightcycle")
        self.assertFalse(project_matches(s, s.get_item(item), "saga"))

    def test_item_with_no_repo_does_not_match_a_short_ref(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertFalse(project_matches(s, s.get_item(item), "lightcycle"))


class TestTextMatches(unittest.TestCase):
    def test_falsy_needle_matches_everything(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertTrue(text_matches(s, s.get_item(item), None))
        self.assertTrue(text_matches(s, s.get_item(item), ""))

    def test_matches_by_id_case_insensitive(self):
        s = FakeStore()
        item_id = s.create_item("item", "a description", id="LC-479")
        self.assertTrue(text_matches(s, s.get_item(item_id), "lc-479"))

    def test_matches_by_title_case_insensitive(self):
        s = FakeStore()
        item_id = s.create_item("Filter the backlog", "a description")
        self.assertTrue(text_matches(s, s.get_item(item_id), "BACKLOG"))

    def test_matches_by_short_project_label_case_insensitive(self):
        s = FakeStore()
        item_id = s.create_item("item", "a description")
        s.add_artifact(item_id, "repo", "kenmclennan/lightcycle")
        self.assertTrue(text_matches(s, s.get_item(item_id), "LIGHTCYCLE"))

    def test_does_not_match_unrelated_text(self):
        s = FakeStore()
        item_id = s.create_item("item", "a description")
        s.add_artifact(item_id, "repo", "kenmclennan/lightcycle")
        self.assertFalse(text_matches(s, s.get_item(item_id), "saga"))


if __name__ == "__main__":
    unittest.main()
