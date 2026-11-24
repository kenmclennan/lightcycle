import unittest

from lightcycle.application.pool import TickInput
from lightcycle.application.pool.no_op_gates import NoOpGhCallGate
from lightcycle.application.work.gate_hold import GateHold
from tests.support.fake_store import FakeStore
from tests.unit.test_pool import FakeConfig, FakeSpawner, FakeWorkers, make_tick
from tests.unit.test_release_hold import _claim, _Flow


def _ready_agent_step(store, shortcode="GRID", role="agent"):
    item = store.create_item("an item", "d", workflow="standard", shortcode=shortcode)
    return store.create_step(stage="build", role=role, item=item)


class TestHeldStepDispatch(unittest.TestCase):
    def _tick(self, store):
        spawner = FakeSpawner()
        make_tick(
            store, FakeWorkers(), spawner, FakeConfig(max_agents=4),
            flow_service=_Flow(store), gh_call_gate=NoOpGhCallGate(),
        ).execute(TickInput(now=1000.0))
        return spawner

    def test_held_ready_agent_step_is_not_spawned_for(self):
        store = FakeStore()
        step = _ready_agent_step(store)
        GateHold(store).place(step, "by hand")

        self.assertEqual(self._tick(store).spawned, [])

    def test_unheld_ready_agent_step_is_still_spawned_for(self):
        store = FakeStore()
        _ready_agent_step(store)

        self.assertEqual(self._tick(store).spawned, ["agent"])

    def test_claim_skips_a_held_step_and_takes_the_next(self):
        store = FakeStore()
        held = _ready_agent_step(store, "AAA")
        free = _ready_agent_step(store, "BBB")
        GateHold(store).place(held, "by hand")

        self.assertEqual(_claim(store).view.step.id, free)
        self.assertIsNone(_claim(store))

    def test_ready_roles_omits_a_held_step(self):
        store = FakeStore()
        held = _ready_agent_step(store, "AAA", role="agent")
        _ready_agent_step(store, "BBB", role="reviewer")
        GateHold(store).place(held, "by hand")

        self.assertEqual(_Flow(store).ready_roles(), ["reviewer"])


if __name__ == "__main__":
    unittest.main()
