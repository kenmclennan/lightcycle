import types
import unittest

from lightcycle.adapters.worker_session import SessionError, plan_session
from lightcycle.domain.pool.worker_session import (
    CLOSE,
    NUDGE,
    SessionPolicy,
    is_terminal_command,
)


class TestPlanSession(unittest.TestCase):
    def _resp(self, pin, step_id="s-1"):
        return types.SimpleNamespace(
            pin=pin, view=types.SimpleNamespace(step=types.SimpleNamespace(id=step_id)))

    def _never_reclaim(self, step_id):
        raise AssertionError("reclaim should not be called: %s" % step_id)

    def test_no_work_yields_no_plan(self):
        self.assertIsNone(
            plan_session(lambda role: None, lambda role, pin: None, self._never_reclaim, "coder"))

    def test_resolves_md_and_model_from_the_claimed_pin(self):
        seen = {}

        def resolve(role, pin):
            seen["args"] = (role, pin)
            return {"meta": {"model": "opus"}, "body": "B-body"}

        plan = plan_session(
            lambda role: self._resp("wfB/x@sha"), resolve, self._never_reclaim, "coder")
        self.assertEqual(seen["args"], ("coder", "wfB/x@sha"))
        self.assertEqual((plan.model, plan.sysprompt), ("opus", "B-body"))

    def test_no_agent_definition_reclaims_the_pre_claim_and_raises(self):
        reclaimed = []
        with self.assertRaises(SessionError):
            plan_session(
                lambda role: self._resp("p", "s-9"), lambda role, pin: None,
                reclaimed.append, "coder")
        self.assertEqual(reclaimed, ["s-9"])

    def test_agent_without_model_reclaims_the_pre_claim_and_raises(self):
        reclaimed = []
        with self.assertRaises(SessionError):
            plan_session(
                lambda role: self._resp("p", "s-9"),
                lambda role, pin: {"meta": {}, "body": "x"},
                reclaimed.append, "coder")
        self.assertEqual(reclaimed, ["s-9"])


class TestTerminalCommand(unittest.TestCase):
    def test_tg_done_is_terminal(self):
        self.assertTrue(is_terminal_command("lc done abc.1 done"))
        self.assertTrue(is_terminal_command("bin/lc done abc.1 rejected"))
        self.assertTrue(is_terminal_command("./bin/lc block xyz --needs foo"))

    def test_non_terminal_tg_commands(self):
        self.assertFalse(is_terminal_command("lc claim coder"))
        self.assertFalse(is_terminal_command("lc reflect abc.1 --feedback ok"))
        self.assertFalse(is_terminal_command("lc show abc.1"))

    def test_empty(self):
        self.assertFalse(is_terminal_command(""))
        self.assertFalse(is_terminal_command(None))


class TestSessionPolicy(unittest.TestCase):
    def test_close_after_terminal_then_result(self):
        p = SessionPolicy()
        p.observe_claimed(True)
        p.observe_command("lc done abc.1 done")
        self.assertEqual(p.on_result(has_open_step=True), CLOSE)

    def test_no_work_exit_closes(self):
        p = SessionPolicy()
        self.assertEqual(p.on_result(has_open_step=False), CLOSE)

    def test_unresolved_task_nudges_indefinitely_never_closes_a_working_worker(self):
        p = SessionPolicy()
        p.observe_claimed(True)
        for _ in range(20):
            self.assertEqual(p.on_result(has_open_step=True), NUDGE)
        self.assertEqual(p.nudges, 20)

    def test_terminal_overrides_nudge(self):
        p = SessionPolicy()
        p.observe_claimed(True)
        self.assertEqual(p.on_result(has_open_step=True), NUDGE)
        p.observe_command("lc block abc.1 --needs x")
        self.assertEqual(p.on_result(has_open_step=True), CLOSE)


if __name__ == "__main__":
    unittest.main()
