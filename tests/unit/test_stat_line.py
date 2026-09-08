import unittest

from lightcycle.adapters.tui.hub import _stat_line_item, _stat_line_step
from tests.support.fake_store import FakeStore

NOW = "2026-01-01T12:00:00"


class _StubFlow:
    def __init__(self, phrases=None):
        self._phrases = phrases or {}

    def display_for(self, node):
        return self._phrases.get(node.stage)


class TestStatLineItem(unittest.TestCase):
    def test_item_blocked_on_a_dependency_is_blank(self):
        store = FakeStore()
        blocker = store.create_item("Blocker", "a description")
        item = store.create_item("Item", "a description")
        store.dep_add(item, blocker)
        store.create_step("s", step="build", role="agent", parent=item)
        node = store.get_node(item)

        self.assertIsNone(_stat_line_item(store, node, store.children(item), _StubFlow(), NOW))

    def test_current_step_blocked_on_a_dependency_is_blank(self):
        store = FakeStore()
        blocker = store.create_item("Blocker", "a description")
        item = store.create_item("Item", "a description")
        step = store.create_step("s", step="build", role="agent", parent=item)
        store.dep_add(step, blocker)
        node = store.get_node(item)

        self.assertIsNone(_stat_line_item(store, node, store.children(item), _StubFlow(), NOW))

    def test_active_item_never_claimed_shows_phrase_and_step_count_only(self):
        store = FakeStore()
        item = store.create_item("Item", "a description")
        store.create_step("s", step="build", role="agent", parent=item)
        node = store.get_node(item)

        self.assertEqual(
            _stat_line_item(store, node, store.children(item), _StubFlow(), NOW), "build · 1 step"
        )

    def test_active_item_pluralises_the_step_count(self):
        store = FakeStore()
        item = store.create_item("Item", "a description")
        store.create_step("s1", step="build", role="agent", parent=item)
        store.create_step("s2", step="test", role="agent", parent=item)
        node = store.get_node(item)

        self.assertIn(
            "2 steps", _stat_line_item(store, node, store.children(item), _StubFlow(), NOW)
        )

    def test_active_item_shows_wall_active_and_cost(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("Item", "a description")
        step = store.create_step("s", step="build", role="agent", parent=item)
        store.claim_ready("agent")
        store.accrue_active_seconds([step], 300)
        store.record_usage(step, 100, 10, 0, 0, 2.91, "list", None)
        store.record_attribution(step, 50, {})
        node = store.get_node(item)

        now = "2026-01-01T10:24:00"
        self.assertEqual(
            _stat_line_item(store, node, store.children(item), _StubFlow(), now),
            "build · 1 step · 24m (5m active) · $2.91",
        )

    def test_finished_item_leads_with_done(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("Item", "a description")
        step = store.create_step("s", step="build", role="agent", parent=item)
        store.claim_ready("agent")
        store.close(step, "done")
        store.close(item, "done")
        store._records[item]["closed_at"] = "2026-01-01T10:30:00"
        node = store.get_node(item)

        self.assertEqual(
            _stat_line_item(store, node, store.children(item), _StubFlow(), "irrelevant-now"),
            "Done · 1 step · 30m (0s active)",
        )


class TestStatLineStepAgent(unittest.TestCase):
    def test_never_claimed_shows_phrase_only(self):
        store = FakeStore()
        item = store.create_item("Item", "a description")
        step = store.create_step("s", step="build", role="agent", parent=item)
        node = store.get_node(step)

        self.assertEqual(_stat_line_step(store, node, _StubFlow(), NOW), "build")

    def test_running_step_shows_wall_active_no_done_segment(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("Item", "a description")
        step = store.create_step("s", step="build", role="agent", parent=item)
        store.claim_ready("agent")
        node = store.get_node(step)

        now = "2026-01-01T10:17:00"
        self.assertEqual(_stat_line_step(store, node, _StubFlow(), now), "build · 17m (0s active)")

    def test_running_step_shows_cost_when_recorded(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("Item", "a description")
        step = store.create_step("s", step="build", role="agent", parent=item)
        store.claim_ready("agent")
        store.accrue_active_seconds([step], 600)
        store.record_usage(step, 100, 10, 0, 0, 1.5, "list", None)
        store.record_attribution(step, 10, {})
        node = store.get_node(step)

        now = "2026-01-01T10:17:00"
        self.assertEqual(
            _stat_line_step(store, node, _StubFlow(), now), "build · 17m (10m active) · $1.50"
        )

    def test_done_step_shows_done_wall_active_and_cost(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("Item", "a description")
        step = store.create_step("s", step="build", role="agent", parent=item)
        store.claim_ready("agent")
        store.accrue_active_seconds([step], 300)
        store.record_usage(step, 100, 10, 0, 0, 2.0, "list", None)
        store.record_attribution(step, 20, {})
        clock["now"] = "2026-01-01T10:30:00"
        store.close(step, "done")
        store._records[step]["closed_at"] = "2026-01-01T10:30:00"
        node = store.get_node(step)

        self.assertEqual(
            _stat_line_step(store, node, _StubFlow(), "irrelevant-now"),
            "build · done · 30m (5m active) · $2.00",
        )

    def test_released_and_reclaimed_shows_elapsed_since_the_reclaim_only(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("Item", "a description")
        step = store.create_step("s", step="write-code", role="agent", parent=item)
        store.claim_ready("agent")
        clock["now"] = "2026-01-01T10:20:00"
        store.reclaim(step)
        clock["now"] = "2026-01-01T11:00:00"
        store.claim_ready("agent")
        node = store.get_node(step)

        now = "2026-01-01T11:24:00"
        self.assertEqual(
            _stat_line_step(store, node, _StubFlow(), now), "write-code · 24m (0s active)"
        )


class TestStatLineStepHuman(unittest.TestCase):
    def test_waiting_gate_shows_wait_since_creation(self):
        clock = {"now": "2026-01-01T09:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("Item", "a description")
        step = store.create_step("await-merge", step="await-merge", role="human", parent=item)
        node = store.get_node(step)

        now = "2026-01-01T09:12:00"
        self.assertEqual(
            _stat_line_step(store, node, _StubFlow(), now), "await-merge · waiting 12m"
        )

    def test_done_gate_shows_done_and_wait(self):
        clock = {"now": "2026-01-01T09:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("Item", "a description")
        step = store.create_step("await-merge", step="await-merge", role="human", parent=item)
        store.close(step, "merged")
        store._records[step]["closed_at"] = "2026-01-01T09:15:00"
        node = store.get_node(step)

        self.assertEqual(
            _stat_line_step(store, node, _StubFlow(), "irrelevant-now"),
            "await-merge · done 15m",
        )

    def test_no_cost_is_ever_shown_for_a_human_step(self):
        clock = {"now": "2026-01-01T09:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("Item", "a description")
        step = store.create_step("await-merge", step="await-merge", role="human", parent=item)
        node = store.get_node(step)

        self.assertNotIn("$", _stat_line_step(store, node, _StubFlow(), "2026-01-01T09:12:00"))

    def test_reassigned_to_human_measures_wait_from_the_park_not_original_creation(self):
        clock = {"now": "2026-01-01T09:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("Item", "a description")
        step = store.create_step("s", step="write-code", role="agent", parent=item)
        clock["now"] = "2026-01-01T09:05:00"
        store.claim_ready("agent")
        clock["now"] = "2026-01-01T11:00:00"
        store.route_to_human(step, "BLOCKED: needs a human decision")
        node = store.get_node(step)

        now = "2026-01-01T11:10:00"
        self.assertEqual(
            _stat_line_step(store, node, _StubFlow(), now), "write-code · waiting 10m"
        )


if __name__ == "__main__":
    unittest.main()
