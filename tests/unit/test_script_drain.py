import unittest
from types import SimpleNamespace

from lightcycle.application.pool import PoolDrainStatusUseCase
from lightcycle.cli import _drain_complete
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.ports.script_runner import ScriptResult
from tests.support.fake_drain import FakeDrain
from tests.support.fake_workers import FakeWorkers
from tests.unit.test_script_stage_usecase import Rig, done

TICK = SimpleNamespace(pool=SimpleNamespace(draining=True, alive=0))


def drain_status(rig):
    drain = FakeDrain()
    drain.request()
    return PoolDrainStatusUseCase(drain, FakeWorkers(), rig.store).execute(True, 0.0)


class TestDrainWaitsForAScriptStage(unittest.TestCase):
    def test_a_running_script_step_holds_the_drain_until_it_completes(self):
        rig = Rig()
        step = rig.step()
        rig.gate.execute(0)

        status = drain_status(rig)

        self.assertEqual(status.engine_steps, 1)
        self.assertFalse(_drain_complete(TICK, status))

        rig.runner.finish(rig.key(step), done("found"))
        rig.gate.execute(1)

        status = drain_status(rig)
        self.assertEqual(status.engine_steps, 0)
        self.assertTrue(_drain_complete(TICK, status))

    def test_a_timed_out_run_parks_and_the_count_drops_to_zero(self):
        rig = Rig(stages={"poll": StepDef(script="scripts/poll.sh", routes={"found": "n"})})
        step = rig.step()
        rig.gate.execute(0)
        self.assertEqual(drain_status(rig).engine_steps, 1)

        rig.runner.finish(rig.key(step), ScriptResult(exit_code=None, timed_out=True))
        rig.gate.execute(1)

        self.assertEqual(rig.store.get_node(step).role, "human")
        self.assertEqual(drain_status(rig).engine_steps, 0)
        self.assertTrue(_drain_complete(TICK, drain_status(rig)))
