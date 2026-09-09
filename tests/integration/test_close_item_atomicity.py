import unittest

from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.domain.work import State
from tests.support.sqlite_store_factory import make_sqlite_store


class TestCloseItemAtomicity(unittest.TestCase):
    def test_partial_failure_leaves_store_in_its_pre_call_state(self):
        store = make_sqlite_store()
        backlog = store.create_step("a backlog item", role="human")
        item = store.create_item("my item", "a description")
        child = store.create_step("build: x", step="build", role="agent", parent=item)
        store.add_artifact(item, "resolves", backlog, internal=True)

        pre_item_state = store.get_node(item).state
        pre_child_state = store.get_node(child).state
        pre_backlog_state = store.get_node(backlog).state
        pre_backlog_artifacts = store.item_artifacts(backlog)

        original_add_artifact = store.add_artifact

        def raising_add_artifact(item_id, atype, value, label=None, internal=False, kind=None):
            if atype == "resolved-by":
                raise RuntimeError("boom")
            return original_add_artifact(
                item_id, atype, value, label=label, internal=internal, kind=kind
            )

        store.add_artifact = raising_add_artifact

        with self.assertRaises(RuntimeError):
            CloseItemUseCase(store, None).execute(
                CloseItemInput(item=item, reason="merged", disposition="completed")
            )

        store.add_artifact = original_add_artifact
        self.assertEqual(store.get_node(item).state, pre_item_state)
        self.assertEqual(store.get_node(child).state, pre_child_state)
        self.assertEqual(store.get_node(backlog).state, pre_backlog_state)
        self.assertEqual(store.item_artifacts(backlog), pre_backlog_artifacts)
        self.assertNotEqual(store.get_node(item).state, State.DONE)


if __name__ == "__main__":
    unittest.main()
