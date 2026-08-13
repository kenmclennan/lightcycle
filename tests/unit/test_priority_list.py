import datetime
import unittest

from lightcycle.adapters.tui.priority_list import _project, format_elapsed
from tests.support.fake_store import FakeStore


class TestFormatElapsed(unittest.TestCase):
    def test_seconds_under_a_minute(self):
        self.assertEqual(format_elapsed(datetime.timedelta(seconds=45)), "45s")

    def test_whole_minutes_under_an_hour(self):
        self.assertEqual(format_elapsed(datetime.timedelta(minutes=14)), "14m")

    def test_hours_and_minutes(self):
        self.assertEqual(
            format_elapsed(datetime.timedelta(hours=1, minutes=7)), "1h 7m"
        )

    def test_sixty_seconds_boundary_is_one_minute(self):
        self.assertEqual(format_elapsed(datetime.timedelta(seconds=60)), "1m")

    def test_sixty_minutes_boundary_is_one_hour(self):
        self.assertEqual(format_elapsed(datetime.timedelta(minutes=60)), "1h 0m")


class TestProject(unittest.TestCase):
    def test_step_with_repo_artifact_on_parent_item_resolves_to_that_value(self):
        store = FakeStore()
        item = store.create_item("item")
        store.add_artifact(item, "repo", "lightcycle")
        step = store.create_step("step", step="build", role="coder", parent=item)

        node = store.get_node(step)
        self.assertEqual(_project(store, node), "lightcycle")

    def test_step_with_no_repo_artifact_on_parent_item_resolves_to_blank(self):
        store = FakeStore()
        item = store.create_item("item")
        step = store.create_step("step", step="build", role="coder", parent=item)

        node = store.get_node(step)
        self.assertEqual(_project(store, node), "")

    def test_step_with_no_parent_resolves_via_its_own_id(self):
        store = FakeStore()
        step = store.create_step("step", step="build", role="coder")
        store.add_artifact(step, "repo", "lightcycle")

        node = store.get_node(step)
        self.assertIsNone(node.parent)
        self.assertEqual(_project(store, node), "lightcycle")
