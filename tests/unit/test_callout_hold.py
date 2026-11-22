import unittest

from lightcycle.application.work.inbox import InboxInput, InboxUseCase
from lightcycle.domain.work import State
from lightcycle.ports.script_runner import ScriptResult
from tests.support.callout_rig import CalloutRig, callout, ok, preflight_failed


class TestCalloutHold(unittest.TestCase):
    def _rows(self, rig):
        use_case = InboxUseCase(rig.store, rig.flow)
        return {r.step.id for r in use_case.execute(InboxInput()).rows}

    def _rig(self, wait):
        rig = CalloutRig([callout("a", "pr", wait=wait)])
        step = rig.gate()
        other = rig.gate(stage="gate")
        rig.use_case.execute(100)
        return rig, step, other

    def test_a_running_waiting_callout_hides_its_gate_and_only_its_gate(self):
        rig, step, other = self._rig(True)
        rows = self._rows(rig)

        self.assertNotIn(step, rows)
        self.assertNotIn(other, rows)

    def test_each_way_a_run_ends_puts_the_gate_back(self):
        outcomes = {
            "ok": lambda rig, key: rig.runner.finish(key, ok()),
            "failed": lambda rig, key: rig.runner.finish(key, ScriptResult(exit_code=1)),
            "timeout": lambda rig, key: rig.runner.finish(
                key, ScriptResult(exit_code=None, timed_out=True)),
            "interrupted": lambda rig, key: rig.runner.orphan_running(),
        }
        for name, end in outcomes.items():
            rig, step, _ = self._rig(True)
            self.assertNotIn(step, self._rows(rig), name)
            rig.pass_preflight(step, 101)
            self.assertNotIn(step, self._rows(rig), name)
            end(rig, rig.key(step))

            rig.use_case.execute(102)

            self.assertIn(step, self._rows(rig), name)

    def test_a_failed_preflight_releases_the_gate(self):
        rig, step, _ = self._rig(True)
        self.assertNotIn(step, self._rows(rig))
        rig.runner.finish(rig.preflight_key(step), preflight_failed(("m", "f")))

        rig.use_case.execute(101)

        self.assertIn(step, self._rows(rig))

    def test_a_non_waiting_callout_never_hides_a_gate(self):
        rig, step, other = self._rig(False)
        self.assertEqual(rig.records(step)["a"]["status"], "running")

        self.assertIn(step, self._rows(rig))

    def test_an_unrelated_gate_with_no_callout_stays_listed(self):
        rig = CalloutRig([callout("a", "description", wait=True)], presents="pr")
        step = rig.gate()
        rig.use_case.execute(100)
        self.assertEqual(rig.store.get_node(step).state, State.WAITING)

        self.assertIn(step, self._rows(rig))


class TestCleanupNeverHolds(unittest.TestCase):
    def test_a_running_cleanup_of_a_waiting_callout_is_not_a_hold(self):
        import time
        from lightcycle.application.work.callout_hold import callout_hold_step_ids

        rig = CalloutRig([callout("a", "pr", wait=True)])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)
        rig.runner.finish(rig.key(step), ok())
        rig.use_case.execute(102)
        rig.store.complete_node(step, "approved")

        rig.use_case.execute(time.time())

        self.assertEqual(rig.records(step)["a"]["cleanup"]["status"], "running")
        self.assertNotIn(step, callout_hold_step_ids(rig.store))
