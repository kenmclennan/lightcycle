import unittest

from lightcycle.application.work.project_of import project_of
from tests.support.fake_store import FakeStore


class TestProjectOf(unittest.TestCase):
    def test_an_item_node_reads_repo_directly_without_calling_get_item(self):
        s = FakeStore()
        item_id = s.create_item("item", "a description")
        s.add_artifact(item_id, "repo", "org/proj")
        item = s.get_item(item_id)

        def _fail(*args, **kwargs):
            raise AssertionError("get_item should not be called for an Item node")

        s.get_item = _fail
        self.assertEqual(project_of(s, item), "org/proj")

    def test_a_step_node_resolves_via_its_parent_item(self):
        s = FakeStore()
        item_id = s.create_item("item", "a description")
        s.add_artifact(item_id, "repo", "org/proj")
        step_id = s.create_step("step", step="write-code", parent=item_id)
        step = s.get_step(step_id)
        self.assertEqual(project_of(s, step), "org/proj")

    def test_a_bare_string_item_id_resolves_via_get_item(self):
        s = FakeStore()
        item_id = s.create_item("item", "a description")
        s.add_artifact(item_id, "repo", "org/proj")
        self.assertEqual(project_of(s, item_id), "org/proj")

    def test_an_unknown_string_id_returns_none(self):
        s = FakeStore()
        self.assertIsNone(project_of(s, "no-such-id"))


if __name__ == "__main__":
    unittest.main()
