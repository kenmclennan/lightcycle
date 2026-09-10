import unittest
from lightcycle.application.errors import UseCaseError
from lightcycle.application.work import ReopenItemInput, ReopenItemUseCase
from tests.support.fake_store import FakeStore


class TestReopenItem(unittest.TestCase):
    def _uc(self):
        store = FakeStore()
        return store, ReopenItemUseCase(store)

    def test_a_reopened_item_is_no_longer_done_and_keeps_its_children(self):
        store, uc = self._uc()
        item = store.create_item("deliver the blueprint", "a description")
        first = store.create_step("s", step="coder", role="agent", parent=item)
        store.complete_node(first, "done")
        store.complete_node(item, "abandoned")
        self.assertEqual(str(store.get_node(item).state), "done")

        uc.execute(ReopenItemInput(item=item))

        node = store.get_node(item)
        self.assertIsNone(node.outcome)
        self.assertIsNone(node.closed_at)
        self.assertEqual(len(store.children(item)), 1)

    def test_a_reopened_item_runs_again_once_a_step_is_filed(self):
        store, uc = self._uc()
        item = store.create_item("deliver the blueprint", "a description")
        store.complete_node(store.create_step("s", step="coder", role="agent", parent=item), "done")
        store.complete_node(item, "abandoned")
        uc.execute(ReopenItemInput(item=item))

        store.create_step("next", step="coder", role="agent", parent=item)

        self.assertNotEqual(str(store.get_node(item).state), "done")

    def test_an_open_item_is_refused_rather_than_silently_ignored(self):
        store, uc = self._uc()
        item = store.create_item("deliver the blueprint", "a description")

        with self.assertRaises(UseCaseError):
            uc.execute(ReopenItemInput(item=item))

    def test_a_step_is_refused_and_points_at_the_verb_that_does_work(self):
        store, uc = self._uc()
        item = store.create_item("i", "a description")
        step = store.create_step("s", step="coder", role="agent", parent=item)
        store.complete_node(step, "done")

        with self.assertRaises(UseCaseError) as e:
            uc.execute(ReopenItemInput(item=step))

        self.assertIn("--state ready", str(e.exception))
