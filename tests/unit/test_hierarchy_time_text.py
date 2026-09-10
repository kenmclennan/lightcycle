import unittest

from lightcycle.adapters.tui.hub import hierarchy_time_text
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step, route_to_human


class TestHierarchyTimeText(unittest.TestCase):
    def test_an_item_root_is_blank(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        node = store.get_node(item)

        self.assertEqual(hierarchy_time_text(store, node, "irrelevant-now"), "")

    def test_an_agent_step_never_claimed_is_blank(self):
        store = FakeStore()
        step = create_owned_step(store, "queued build", step="build", role="agent")
        node = store.get_node(step)

        self.assertEqual(hierarchy_time_text(store, node, "irrelevant-now"), "")

    def test_an_agent_step_claimed_still_running_shows_wall_and_active(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        step = create_owned_step(store, "building", step="build", role="agent")
        store.claim_ready("agent")
        store.accrue_active_seconds([step], 600)
        node = store.get_node(step)

        now = "2026-01-01T10:17:00"
        self.assertEqual(hierarchy_time_text(store, node, now), "17m (10m active)")

    def test_released_and_reclaimed_still_running_shows_elapsed_since_the_second_claim_only(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        step = create_owned_step(store, "building", step="build", role="agent")
        store.claim_ready("agent")
        clock["now"] = "2026-01-01T10:20:00"
        store.reclaim(step)
        clock["now"] = "2026-01-01T11:00:00"
        store.claim_ready("agent")
        node = store.get_node(step)

        now = "2026-01-01T11:24:00"
        self.assertEqual(hierarchy_time_text(store, node, now), "24m (0s active)")

    def test_a_done_agent_step_shows_wall_and_active_from_claim_to_done(self):
        clock = {"now": "2026-01-01T10:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        step = create_owned_step(store, "building", step="build", role="agent")
        store.claim_ready("agent")
        store.accrue_active_seconds([step], 300)
        clock["now"] = "2026-01-01T10:30:00"
        store.complete_node(step, "done")
        store._records[step]["closed_at"] = "2026-01-01T10:30:00"
        node = store.get_node(step)

        self.assertEqual(
            hierarchy_time_text(store, node, "irrelevant-now"), "30m (5m active)"
        )

    def test_a_freshly_created_human_step_shows_elapsed_only_measured_from_creation(self):
        clock = {"now": "2026-01-01T09:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        step = create_owned_step(store, "await-merge", step="await-merge", role="human")
        node = store.get_node(step)

        now = "2026-01-01T09:12:00"
        self.assertEqual(hierarchy_time_text(store, node, now), "12m")

    def test_a_step_reassigned_to_human_mid_flow_measures_wait_from_the_park_not_creation(self):
        clock = {"now": "2026-01-01T09:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        step = create_owned_step(store, "s", step="write-code", role="agent")
        clock["now"] = "2026-01-01T09:05:00"
        store.claim_ready("agent")
        clock["now"] = "2026-01-01T11:00:00"
        route_to_human(store, step, "BLOCKED: needs a human decision")
        node = store.get_node(step)

        now = "2026-01-01T11:10:00"
        self.assertEqual(hierarchy_time_text(store, node, now), "10m")

    def test_a_done_human_step_shows_elapsed_from_wait_start_to_closed_at(self):
        clock = {"now": "2026-01-01T09:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        step = create_owned_step(store, "await-merge", step="await-merge", role="human")
        store.complete_node(step, "merged")
        store._records[step]["closed_at"] = "2026-01-01T09:15:00"
        node = store.get_node(step)

        self.assertEqual(hierarchy_time_text(store, node, "irrelevant-now"), "15m")

    def test_a_step_with_no_recorded_role_is_treated_as_human(self):
        clock = {"now": "2026-01-01T09:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        step = create_owned_step(store, "s", step="await-merge")
        node = store.get_node(step)

        now = "2026-01-01T09:12:00"
        self.assertEqual(hierarchy_time_text(store, node, now), "12m")


if __name__ == "__main__":
    unittest.main()
