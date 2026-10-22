import unittest

from lightcycle.application.flow import ClaimInput, ClaimStepUseCase
from lightcycle.application.pool import TickInput
from lightcycle.application.pool.no_op_gates import NoOpGhCallGate
from lightcycle.application.pool.note_release_holds import NoteReleaseHoldsUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.close_item import RELEASE_PENDING_LABEL
from lightcycle.application.work.release_holds import ReleaseHolds
from lightcycle.domain.flow.step_def import StepDef
from tests.support.fake_fs import FakeFs
from tests.support.fake_github_budget_status import FakeGithubBudgetStatus
from tests.support.fake_store import FakeStore
from tests.unit.test_flow_usecases import FakeConfig as ClaimConfig
from tests.unit.test_flow_usecases import FakeWorkers as ClaimWorkers
from tests.unit.test_flow_usecases import FakeWorktrees
from tests.unit.test_github_budget import _budget
from tests.unit.test_pool import FakeConfig, FakeSpawner, FakeWorkers, make_tick
from tests.unit.test_script_stage_usecase import PIN, Rig


class _Flow(FlowService):
    def __init__(self, store, defs=None):
        super().__init__(FakeFs({}), store)
        self._defs = defs or {}

    def unpinned_workflow(self, node):
        return None

    def flow_for(self, node):
        defs = self._defs
        return type("F", (), {"step_def": lambda _self, stage: defs.get(stage, StepDef())})()


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _marked_item(store, title="held"):
    item = store.create_item(title, "d", workflow="standard", shortcode="GRID")
    store.label_add(item, RELEASE_PENDING_LABEL)
    return item


def _claim(store, role="agent"):
    flow = _Flow(store)
    uc = ClaimStepUseCase(
        store, flow, FakeWorktrees(), ClaimWorkers(), ClaimConfig(),
        _budget(FakeGithubBudgetStatus(), flow))
    return uc.execute(ClaimInput(role=role))


class TestHeldIds(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.defs = {
            "script-ws": StepDef(script="s.sh", workspace="code"),
            "script-plain": StepDef(script="s.sh"),
        }
        self.flow = _Flow(self.store, self.defs)
        self.holds = ReleaseHolds(self.store, self.flow)

    def test_an_agent_step_of_a_marked_item_is_held(self):
        step = self.store.create_step(stage="build", role="agent", item=_marked_item(self.store))

        self.assertEqual(self.holds.held_ids(self.store.ready_steps()), {step})

    def test_an_engine_step_without_a_script_is_not_held(self):
        self.store.create_step(stage="poll-ci", role="engine", item=_marked_item(self.store))

        self.assertEqual(self.holds.held_ids(self.store.ready_steps()), set())

    def test_a_workspace_script_is_held_and_a_plain_script_is_not(self):
        item = _marked_item(self.store)
        held = self.store.create_step(stage="script-ws", role="engine", item=item)
        self.store.create_step(stage="script-plain", role="engine", item=item)

        self.assertEqual(self.holds.held_ids(self.store.ready_steps()), {held})

    def test_an_unmarked_item_is_not_held(self):
        item = self.store.create_item("free", "d", workflow="standard", shortcode="GRID")
        self.store.create_step(stage="build", role="agent", item=item)

        self.assertEqual(self.holds.held_ids(self.store.ready_steps()), set())

    def test_an_unpinned_engine_step_is_not_held(self):
        flow = _Flow(self.store, self.defs)
        flow.unpinned_workflow = lambda node: "name"
        self.store.create_step(stage="script-ws", role="engine", item=_marked_item(self.store))

        self.assertEqual(
            ReleaseHolds(self.store, flow).held_ids(self.store.ready_steps()), set())


class TestClaimHold(unittest.TestCase):
    def test_a_marked_items_step_is_not_claimed_and_another_items_is(self):
        store = FakeStore()
        store.create_step(stage="build", role="agent", item=_marked_item(store))
        free = store.create_item("free", "d", workflow="standard", shortcode="GRID")
        other = store.create_step(stage="build", role="agent", item=free)

        self.assertEqual(_claim(store).view.step.id, other)
        self.assertIsNone(_claim(store))

    def test_the_claim_succeeds_once_the_marker_is_cleared(self):
        store = FakeStore()
        item = _marked_item(store)
        step = store.create_step(stage="build", role="agent", item=item)

        self.assertIsNone(_claim(store))
        store.label_remove(item, RELEASE_PENDING_LABEL)

        self.assertEqual(_claim(store).view.step.id, step)


class TestScriptStageHold(unittest.TestCase):
    def _rig(self):
        return Rig(stages={
            "ws": StepDef(script="scripts/a.sh", workspace="code", routes={"found": "next"}),
            "plain": StepDef(script="scripts/b.sh", routes={"found": "next"}),
        }, worktree="/wt")

    def _marked_step(self, rig, stage):
        item = rig.store.create_item("t", "d", workflow=PIN, shortcode="APP")
        rig.store.add_artifact(item, "brief", "hello")
        rig.store.label_add(item, RELEASE_PENDING_LABEL)
        return item, rig.store.create_step(stage=stage, role="engine", item=item)

    def test_a_workspace_script_of_a_marked_item_stays_queued_until_the_label_clears(self):
        rig = self._rig()
        item, step = self._marked_step(rig, "ws")

        self.assertEqual(rig.gate.execute(0).started, [])
        rig.store.label_remove(item, RELEASE_PENDING_LABEL)

        self.assertEqual(rig.gate.execute(1).started, [rig.key(step)])

    def test_a_plain_script_of_a_marked_item_still_starts(self):
        rig = self._rig()
        _item, step = self._marked_step(rig, "plain")

        self.assertEqual(rig.gate.execute(0).started, [rig.key(step)])


class TestTickAndReadyRolesHold(unittest.TestCase):
    def test_no_worker_is_spawned_for_a_role_whose_ready_steps_are_all_held(self):
        store = FakeStore()
        store.create_step(stage="build", role="agent", item=_marked_item(store))
        spawner = FakeSpawner()
        tick = make_tick(
            store, FakeWorkers(), spawner, FakeConfig(max_agents=4),
            flow_service=_Flow(store), gh_call_gate=NoOpGhCallGate())

        tick.execute(TickInput(now=1000.0))

        self.assertEqual(spawner.spawned, [])

    def test_a_worker_is_spawned_for_a_free_items_step_in_the_same_tick(self):
        store = FakeStore()
        store.create_step(stage="build", role="agent", item=_marked_item(store))
        free = store.create_item("free", "d", workflow="standard", shortcode="GRID")
        store.create_step(stage="build", role="agent", item=free)
        spawner = FakeSpawner()
        tick = make_tick(
            store, FakeWorkers(), spawner, FakeConfig(max_agents=4),
            flow_service=_Flow(store), gh_call_gate=NoOpGhCallGate())

        tick.execute(TickInput(now=1000.0))

        self.assertEqual(spawner.spawned, ["agent"])

    def test_ready_roles_omits_a_role_with_only_held_steps(self):
        store = FakeStore()
        item = _marked_item(store)
        store.create_step(stage="build", role="agent", item=item)
        flow = _Flow(store)

        self.assertEqual(flow.ready_roles(), [])
        store.label_remove(item, RELEASE_PENDING_LABEL)

        self.assertEqual(flow.ready_roles(), ["agent"])


class TestNoteReleaseHolds(unittest.TestCase):
    BOUND = 60

    def _rig(self):
        store = FakeStore()
        clock = _Clock()
        note = NoteReleaseHoldsUseCase(
            store, ReleaseHolds(store, _Flow(store)), clock, lambda: self.BOUND)
        return store, clock, note

    def _notes(self, store, step):
        return [l for l in (store.get_node(step).notes or "").splitlines()
                if "release-hold-note-seconds" in l]

    def test_no_note_before_the_bound_and_one_exactly_at_it(self):
        store, clock, note = self._rig()
        step = store.create_step(stage="build", role="agent", item=_marked_item(store))

        note.execute()
        clock.now += self.BOUND - 1
        note.execute()
        self.assertEqual(self._notes(store, step), [])
        clock.now += 1
        note.execute()

        self.assertEqual(len(self._notes(store, step)), 1)

    def test_the_note_repeats_at_the_same_interval(self):
        store, clock, note = self._rig()
        step = store.create_step(stage="build", role="agent", item=_marked_item(store))
        note.execute()
        clock.now += self.BOUND
        note.execute()
        clock.now += self.BOUND - 1
        note.execute()
        self.assertIn("(x1,", self._notes(store, step)[0])
        clock.now += 1
        note.execute()

        self.assertIn("(x2,", self._notes(store, step)[0])

    def test_no_note_once_the_label_is_cleared(self):
        store, clock, note = self._rig()
        item = _marked_item(store)
        step = store.create_step(stage="build", role="agent", item=item)
        note.execute()
        store.label_remove(item, RELEASE_PENDING_LABEL)
        clock.now += self.BOUND * 3
        note.execute()

        self.assertEqual(self._notes(store, step), [])

    def test_only_the_marked_items_steps_carry_the_note(self):
        store, clock, note = self._rig()
        held = store.create_step(stage="build", role="agent", item=_marked_item(store))
        free = store.create_item("free", "d", workflow="standard", shortcode="GRID")
        other = store.create_step(stage="build", role="agent", item=free)
        note.execute()
        clock.now += self.BOUND
        note.execute()

        self.assertEqual(len(self._notes(store, held)), 1)
        self.assertEqual(self._notes(store, other), [])


if __name__ == "__main__":
    unittest.main()
