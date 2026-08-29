import json
import threading
import types
import unittest

from lightcycle.adapters.worker_session import SessionError, dispatch_event, plan_session
from lightcycle.domain.pool.rate_limit import parse_rate_limit_event
from lightcycle.domain.pool.worker_session import (
    CLOSE,
    MAX_NUDGES,
    NUDGE,
    SessionPolicy,
    is_terminal_command,
)

REJECTED_LINE = (
    '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":1788009600,'
    '"rateLimitType":"five_hour","overageStatus":"rejected","overageDisabledReason":'
    '"org_level_disabled","isUsingOverage":false},"uuid":"36f969c3-ce27-4c90-b9e4-4d04f05fa4df",'
    '"session_id":"49d8ac0f-6398-40c9-b723-1a3a21918333"}'
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

    def test_unresolved_task_nudges_up_to_the_cap_then_closes(self):
        p = SessionPolicy()
        p.observe_claimed(True)
        for _ in range(MAX_NUDGES):
            self.assertEqual(p.on_result(has_open_step=True), NUDGE)
        self.assertEqual(p.on_result(has_open_step=True), CLOSE)

    def test_terminal_overrides_nudge(self):
        p = SessionPolicy()
        p.observe_claimed(True)
        self.assertEqual(p.on_result(has_open_step=True), NUDGE)
        p.observe_command("lc block abc.1 --needs x")
        self.assertEqual(p.on_result(has_open_step=True), CLOSE)

    def test_rejected_rate_limit_closes_even_with_open_step_and_claimed(self):
        p = SessionPolicy()
        p.observe_claimed(True)
        p.observe_rate_limit(parse_rate_limit_event(REJECTED_LINE))
        self.assertEqual(p.on_result(has_open_step=True), CLOSE)

    def test_non_rejected_event_does_not_close(self):
        allowed_line = (
            '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}'
        )
        p = SessionPolicy()
        p.observe_claimed(True)
        p.observe_rate_limit(parse_rate_limit_event(allowed_line))
        self.assertEqual(p.on_result(has_open_step=True), NUDGE)

    def test_none_event_does_not_close(self):
        p = SessionPolicy()
        p.observe_claimed(True)
        p.observe_rate_limit(None)
        self.assertEqual(p.on_result(has_open_step=True), NUDGE)


class TestDispatchEvent(unittest.TestCase):
    def test_rejected_rate_limit_line_forwards_to_policy_and_closes(self):
        policy = SessionPolicy()
        policy.observe_claimed(True)
        counters = {"results": 0}
        lock = threading.Lock()
        d = json.loads(REJECTED_LINE)
        dispatch_event(d, REJECTED_LINE, policy, counters, lock)
        self.assertEqual(policy.on_result(has_open_step=True), CLOSE)

    def test_result_line_increments_counter(self):
        policy = SessionPolicy()
        counters = {"results": 0}
        lock = threading.Lock()
        line = '{"type":"result"}'
        dispatch_event(json.loads(line), line, policy, counters, lock)
        self.assertEqual(counters["results"], 1)


if __name__ == "__main__":
    unittest.main()
