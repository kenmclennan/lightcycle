import datetime
import unittest

from lightcycle.adapters.tui.done_list import build_done_rows
from lightcycle.adapters.tui.hub import COST_NOT_RECORDED
from lightcycle.application.work.done import DoneInput, DoneUseCase
from tests.support.fake_store import FakeStore

_NOW = datetime.datetime(2026, 1, 5).astimezone()


def _done_rows(store, cache=None):
    resp = DoneUseCase(store).execute(DoneInput())
    return build_done_rows(store, resp.rows, _NOW, cache if cache is not None else {})


class TestBuildDoneRowsCost(unittest.TestCase):
    def test_a_completed_step_with_recorded_usage_produces_cost_and_time_text(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        step = store.create_step(step="build", role="agent", parent=item)
        store.claim_ready("agent")
        store.accrue_active_seconds([step], 540)
        store.record_usage(step, 100, 10, 0, 0, 3.75, "list", None)
        store.complete_node(step, "done")
        store.complete_node(item, "merged")

        rows = _done_rows(store)

        self.assertEqual(rows[0].cost, "$3.75")
        self.assertEqual(rows[0].time, "0s (9m active)")

    def test_an_item_with_no_steps_has_blank_cost_and_time(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        store.complete_node(item, "merged")

        rows = _done_rows(store)

        self.assertEqual(rows[0].cost, "")
        self.assertEqual(rows[0].time, "")

    def test_a_step_that_ran_with_no_recorded_cost_shows_the_not_recorded_placeholder(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        step = store.create_step(step="build", role="agent", parent=item)
        store.claim_ready("agent")
        store.record_attribution(step, 50, {})
        store.complete_node(step, "done")
        store.complete_node(item, "merged")

        rows = _done_rows(store)

        self.assertEqual(rows[0].cost, COST_NOT_RECORDED)


class TestBuildDoneRowsCache(unittest.TestCase):
    def _closed_store(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        step = store.create_step(step="build", role="agent", parent=item)
        store.claim_ready("agent")
        store.accrue_active_seconds([step], 300)
        store.record_usage(step, 100, 10, 0, 0, 2.50, "list", None)
        store.complete_node(step, "done")
        store.complete_node(item, "merged")
        return store, item

    def _spy_store_calls(self, store):
        calls = {"children": 0, "history": 0}
        original_children = store.children
        original_history = store.history

        def counted_children(item_id):
            calls["children"] += 1
            return original_children(item_id)

        def counted_history(tid):
            calls["history"] += 1
            return original_history(tid)

        store.children = counted_children
        store.history = counted_history
        return calls

    def test_a_second_call_with_the_same_cache_and_unchanged_items_hits_the_cache(self):
        store, _item = self._closed_store()
        cache = {}
        _done_rows(store, cache=cache)
        calls = self._spy_store_calls(store)

        _done_rows(store, cache=cache)

        self.assertEqual(calls["children"], 0)
        self.assertEqual(calls["history"], 0)

    def test_a_changed_closed_at_is_treated_as_a_fresh_computation(self):
        store, item = self._closed_store()
        cache = {}
        _done_rows(store, cache=cache)
        calls = self._spy_store_calls(store)

        store._records[item]["closed_at"] = "2026-02-01T00:00:00+00:00"
        rows = _done_rows(store, cache=cache)

        self.assertEqual(calls["children"], 1)
        self.assertEqual(rows[0].cost, "$2.50")


if __name__ == "__main__":
    unittest.main()
