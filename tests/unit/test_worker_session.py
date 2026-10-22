import ast
import json
import pathlib
import os
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import queue
import sqlite3

import lightcycle.adapters.worker_session as worker_session_mod
from lightcycle.adapters.worker_session import (
    EXIT_GRACE_SECONDS,
    MAX_LINE_BYTES,
    SessionError,
    RESULT,
    SESSION_ID,
    dispatch_event,
    drain,
    has_open_step,
    plan_session,
    poll_decision,
    run,
    session_cwd,
)
from lightcycle.adapters.claude_stream import (
    parse_rate_limit_event, saw_session_activity,
)
from lightcycle.domain.guidance.guidance import GuidanceSelection
from lightcycle.ports.workflow_bundle import StepPrompt
from lightcycle.domain.pool.worker_session import (
    CLOSE,
    MAX_NUDGES,
    NUDGE,
    SessionPolicy,
)

REJECTED_LINE = (
    '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":1788009600,'
    '"rateLimitType":"five_hour","overageStatus":"rejected","overageDisabledReason":'
    '"org_level_disabled","isUsingOverage":false},"uuid":"36f969c3-ce27-4c90-b9e4-4d04f05fa4df",'
    '"session_id":"49d8ac0f-6398-40c9-b723-1a3a21918333"}'
)


class TestPlanSession(unittest.TestCase):
    def _resp(self, pin, step_id="s-1", workspace=None, step_file="write-code", stage="write-code"):
        return types.SimpleNamespace(
            pin=pin,
            view=types.SimpleNamespace(step=types.SimpleNamespace(id=step_id, stage=stage)),
            workspace=workspace, step_file=step_file)

    def _never_reclaim(self, step_id):
        raise AssertionError("reclaim should not be called: %s" % step_id)

    def test_no_work_yields_no_plan(self):
        self.assertIsNone(
            plan_session(lambda role: None, lambda f, pin: None, self._never_reclaim, "agent"))

    def test_resolves_the_step_file_from_the_claim_not_the_spawned_role(self):
        seen = {}

        def resolve(step_file, pin):
            seen["args"] = (step_file, pin)
            return StepPrompt(meta={"model": "opus"}, body="B-body")

        plan = plan_session(
            lambda role: self._resp("wfB/x@sha", step_file="write-code.md"),
            resolve, self._never_reclaim, "agent")
        self.assertEqual(seen["args"], ("write-code.md", "wfB/x@sha"))
        self.assertEqual((plan.model, plan.sysprompt), ("opus", "B-body"))

    def test_the_plan_carries_the_claimed_stage_not_the_spawned_role(self):
        plan = plan_session(
            lambda role: self._resp("wfB/x@sha", stage="review-code"),
            lambda f, pin: StepPrompt(meta={"model": "opus"}, body="B"),
            self._never_reclaim, "agent")
        self.assertEqual(plan.stage, "review-code")

    def test_no_agent_definition_reclaims_the_pre_claim_and_raises(self):
        reclaimed = []
        with self.assertRaises(SessionError):
            plan_session(
                lambda role: self._resp("p", "s-9"), lambda f, pin: None,
                reclaimed.append, "agent")
        self.assertEqual(reclaimed, ["s-9"])

    def test_agent_without_model_reclaims_the_pre_claim_and_raises(self):
        reclaimed = []
        with self.assertRaises(SessionError):
            plan_session(
                lambda role: self._resp("p", "s-9"),
                lambda f, pin: StepPrompt(meta={}, body="x"),
                reclaimed.append, "agent")
        self.assertEqual(reclaimed, ["s-9"])

    def test_carries_workspace_through_when_present(self):
        plan = plan_session(
            lambda role: self._resp("wfB/x@sha", workspace="/work/item-1"),
            lambda f, pin: StepPrompt(meta={"model": "opus"}, body="B-body"),
            self._never_reclaim, "agent")
        self.assertEqual(plan.workspace, "/work/item-1")

    def test_default_selection_leaves_the_system_prompt_byte_identical(self):
        plan = plan_session(
            lambda role: self._resp("wfB/x@sha"),
            lambda f, pin: StepPrompt(meta={"model": "opus"}, body="B-body\n\n"),
            self._never_reclaim, "agent")
        self.assertEqual(plan.sysprompt, "B-body\n\n")
        self.assertEqual((plan.guidance_delivered, plan.guidance_skipped), ((), ()))

    def test_a_selection_is_appended_after_the_step_body(self):
        selection = GuidanceSelection(
            section="## Guidance for this project\n\nx", delivered=("a",), skipped=("b",),
            notes=("n",))
        seen = []
        plan = plan_session(
            lambda role: self._resp("wfB/x@sha"),
            lambda f, pin: StepPrompt(meta={"model": "opus"}, body="B-body\n\n"),
            self._never_reclaim, "agent", guidance=lambda resp: seen.append(resp) or selection)
        self.assertEqual(plan.sysprompt, "B-body\n\n## Guidance for this project\n\nx")
        self.assertEqual(
            (plan.guidance_delivered, plan.guidance_skipped, plan.guidance_notes, plan.guidance_recorded),
            (("a",), ("b",), ("n",), True))
        self.assertEqual(len(seen), 1)

    def test_a_raising_selection_still_plans_with_an_unmodified_prompt_and_a_note(self):
        def boom(resp):
            raise RuntimeError("kaboom")

        plan = plan_session(
            lambda role: self._resp("wfB/x@sha"),
            lambda f, pin: StepPrompt(meta={"model": "opus"}, body="B-body"),
            self._never_reclaim, "agent", guidance=boom)
        self.assertEqual(plan.sysprompt, "B-body")
        self.assertEqual(plan.guidance_notes, ("kaboom",))
        self.assertFalse(plan.guidance_recorded)

    def test_workspace_is_none_when_claim_has_none(self):
        plan = plan_session(
            lambda role: self._resp("wfB/x@sha"),
            lambda f, pin: StepPrompt(meta={"model": "opus"}, body="B-body"),
            self._never_reclaim, "agent")
        self.assertIsNone(plan.workspace)

    def test_carries_the_step_id_through(self):
        plan = plan_session(
            lambda role: self._resp("wfB/x@sha", step_id="s-42"),
            lambda f, pin: StepPrompt(meta={"model": "opus"}, body="B-body"),
            self._never_reclaim, "agent")
        self.assertEqual(plan.step_id, "s-42")


class TestSawSessionActivity(unittest.TestCase):
    def test_true_for_an_assistant_event(self):
        line = json.dumps({"type": "assistant", "message": {"content": []}})
        self.assertTrue(saw_session_activity([line]))

    def test_true_for_a_result_event(self):
        self.assertTrue(saw_session_activity(['{"type":"result","subtype":"success"}']))

    def test_false_for_a_rate_limit_only_log(self):
        self.assertFalse(saw_session_activity([REJECTED_LINE]))

    def test_false_for_an_empty_log(self):
        self.assertFalse(saw_session_activity([]))

    def test_false_for_plain_non_json_diagnostic_text(self):
        lines = [
            "session started",
            "Failed to authenticate: OAuth session expired and could not be refreshed",
            "error: api_error",
        ]
        self.assertFalse(saw_session_activity(lines))


class TestSessionPolicy(unittest.TestCase):
    def test_a_step_no_longer_in_progress_closes(self):
        self.assertEqual(SessionPolicy().on_result(has_open_step=False), CLOSE)

    def test_a_step_still_in_progress_nudges_whatever_commands_were_run(self):
        self.assertEqual(SessionPolicy().on_result(has_open_step=True), NUDGE)

    def test_unresolved_task_nudges_up_to_the_cap_then_closes(self):
        p = SessionPolicy()
        for _ in range(MAX_NUDGES):
            self.assertEqual(p.on_result(has_open_step=True), NUDGE)
        self.assertEqual(p.on_result(has_open_step=True), CLOSE)

    def test_rejected_rate_limit_closes_even_with_open_step_and_claimed(self):
        p = SessionPolicy()
        p.observe_rate_limit(parse_rate_limit_event([REJECTED_LINE]))
        self.assertEqual(p.on_result(has_open_step=True), CLOSE)

    def test_non_rejected_event_does_not_close(self):
        allowed_line = (
            '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}'
        )
        p = SessionPolicy()
        p.observe_rate_limit(parse_rate_limit_event([allowed_line]))
        self.assertEqual(p.on_result(has_open_step=True), NUDGE)

    def test_none_event_does_not_close(self):
        p = SessionPolicy()
        p.observe_rate_limit(None)
        self.assertEqual(p.on_result(has_open_step=True), NUDGE)

    def test_fresh_policy_has_no_session_id(self):
        self.assertIsNone(SessionPolicy().session_id)

    def test_observe_session_id_sets_it(self):
        p = SessionPolicy()
        p.observe_session_id("sess-abc")
        self.assertEqual(p.session_id, "sess-abc")

    def test_observe_session_id_with_none_leaves_it_unset(self):
        p = SessionPolicy()
        p.observe_session_id(None)
        self.assertIsNone(p.session_id)


class TestSessionCwd(unittest.TestCase):
    def test_present_workspace_returned_unchanged(self):
        with session_cwd("/some/workspace") as cwd:
            self.assertEqual(cwd, "/some/workspace")

    def test_missing_workspace_creates_fresh_scratch_dir_and_removes_it_on_exit(self):
        with session_cwd(None) as created:
            self.assertTrue(os.path.isdir(created))
            tmp_root = os.path.realpath(tempfile.gettempdir())
            self.assertEqual(
                os.path.commonpath([os.path.realpath(created), tmp_root]), tmp_root
            )
        self.assertFalse(os.path.isdir(created))

    def test_missing_workspace_is_fresh_per_call(self):
        with session_cwd(None) as first, session_cwd(None) as second:
            self.assertNotEqual(first, second)

    def test_missing_workspace_temp_dir_removed_even_when_the_body_raises(self):
        created = None
        with self.assertRaises(RuntimeError):
            with session_cwd(None) as cwd:
                created = cwd
                self.assertTrue(os.path.isdir(created))
                raise RuntimeError("boom")
        self.assertFalse(os.path.isdir(created))


def _open():
    return True


def _fail_open_step():
    raise AssertionError("open_step should not be called")


class TestPollDecision(unittest.TestCase):
    def test_pending_result_asks_the_store_whether_the_step_is_open(self):
        events = queue.Queue()
        events.put((RESULT, None))
        asked = []

        def open_step():
            asked.append(True)
            return True

        poll_decision(open_step, SessionPolicy(), events)
        self.assertEqual(asked, [True])

    def test_no_pending_result_skips_lookup_and_returns_none(self):
        decision = poll_decision(_fail_open_step, SessionPolicy(), queue.Queue())
        self.assertIsNone(decision)

    def test_a_result_is_consumed_so_the_next_poll_is_quiet(self):
        policy = SessionPolicy()
        events = queue.Queue()
        events.put((RESULT, None))
        first = poll_decision(_open, policy, events)
        second = poll_decision(_fail_open_step, policy, events)
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_a_session_whose_done_was_refused_is_nudged_not_closed(self):
        events = queue.Queue()
        events.put((RESULT, None))
        self.assertEqual(poll_decision(_open, SessionPolicy(), events), NUDGE)

    def test_a_session_whose_done_named_another_step_is_nudged_not_closed(self):
        events = queue.Queue()
        events.put((RESULT, None))
        self.assertEqual(poll_decision(_open, SessionPolicy(), events), NUDGE)

    def test_a_session_whose_own_step_is_closed_is_closed(self):
        events = queue.Queue()
        events.put((RESULT, None))
        self.assertEqual(poll_decision(lambda: False, SessionPolicy(), events), CLOSE)


class _FakeStdout:
    def __init__(self, text=""):
        self._buf = text

    def readline(self, size=-1):
        if not self._buf:
            return ""
        nl = self._buf.find("\n")
        if nl != -1 and (not size or size <= 0 or nl + 1 <= size):
            line = self._buf[: nl + 1]
        elif size and size > 0:
            line = self._buf[:size]
        else:
            line = self._buf
        self._buf = self._buf[len(line):]
        return line


class TestRun(unittest.TestCase):
    def _fake_popen(self, captured, stdout_text=""):
        def popen(cmd, cwd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = cwd
            proc = MagicMock()
            proc.poll.return_value = 0
            proc.stdout = _FakeStdout(stdout_text)
            proc.wait.return_value = 0
            return proc
        return popen

    def test_env_is_passed_to_popen(self):
        seen = {}

        def popen(cmd, cwd, **kwargs):
            seen.update(kwargs)
            return self._fake_popen({})(cmd, cwd, **kwargs)

        with patch("lightcycle.adapters.worker_session.subprocess.Popen", popen):
            run("/d", "/w", "coder", "opus", "sys", 5, env={"A": "1"}, open_step=_open)
            self.assertEqual(seen["env"], {"A": "1"})
            run("/d", "/w", "coder", "opus", "sys", 5, open_step=_open)
            self.assertIsNone(seen["env"])

    def test_launches_with_given_cwd_and_add_dir(self):
        captured = {}
        with patch("lightcycle.adapters.worker_session.subprocess.Popen",
                    self._fake_popen(captured)):
            run("/data/root", "/work/item-1", "coder", "opus", "sys", 5, open_step=_open)
        self.assertEqual(captured["cwd"], "/work/item-1")
        cmd = captured["cmd"]
        self.assertIn("--add-dir", cmd)
        self.assertEqual(cmd[cmd.index("--add-dir") + 1], "/data/root")

    def test_launches_with_fallback_cwd_distinct_from_add_dir(self):
        captured = {}
        with patch("lightcycle.adapters.worker_session.subprocess.Popen",
                    self._fake_popen(captured)):
            run("/data/root", "/tmp/lc-worker-xyz", "coder", "opus", "sys", 5, open_step=_open)
        self.assertEqual(captured["cwd"], "/tmp/lc-worker-xyz")

    def test_reader_bounds_an_unterminated_line_instead_of_growing_without_limit(self):
        captured = {}
        huge = "x" * (MAX_LINE_BYTES + 100)
        with patch("lightcycle.adapters.worker_session.subprocess.Popen",
                    self._fake_popen(captured, stdout_text=huge)):
            rc = run("/data/root", "/work/item-1", "coder", "opus", "sys", 5, open_step=_open)
        self.assertEqual(rc, 0)

    class _NeverExitsProc:
        def __init__(self):
            self.stdout = _FakeStdout("")
            self.stdin = MagicMock()
            self.terminate_calls = 0
            self.kill_calls = 0

        def poll(self):
            return None

        def terminate(self):
            self.terminate_calls += 1

        def kill(self):
            self.kill_calls += 1

        def wait(self):
            return -9

    class _CountingClock:
        def __init__(self):
            self.calls = 0

        def __call__(self):
            self.calls += 1
            return self.calls

    def test_session_timeout_fires_from_the_injected_clock_alone(self):
        proc = self._NeverExitsProc()

        def popen(cmd, cwd, **kwargs):
            return proc

        clock = self._CountingClock()
        with patch("lightcycle.adapters.worker_session.subprocess.Popen", popen), \
                patch("lightcycle.adapters.worker_session.time.sleep"):
            run("/data/root", "/work/item-1", "coder", "opus", "sys", 0, clock=clock, open_step=_open)
        self.assertEqual(proc.terminate_calls, 2)
        self.assertEqual(proc.kill_calls, 1)

    def test_exit_grace_deadline_is_computed_from_the_injected_clock_not_wall_time(self):
        proc = self._NeverExitsProc()

        def popen(cmd, cwd, **kwargs):
            return proc

        clock = self._CountingClock()
        with patch("lightcycle.adapters.worker_session.subprocess.Popen", popen), \
                patch("lightcycle.adapters.worker_session.time.sleep"):
            run("/data/root", "/work/item-1", "coder", "opus", "sys", 0, clock=clock, open_step=_open)
        self.assertGreaterEqual(clock.calls, EXIT_GRACE_SECONDS)

    def test_time_time_is_never_called(self):
        captured = {}
        with patch("lightcycle.adapters.worker_session.subprocess.Popen",
                    self._fake_popen(captured)), \
                patch("lightcycle.adapters.worker_session.time.time") as faketime:
            run("/data/root", "/work/item-1", "coder", "opus", "sys", 5, open_step=_open)
        faketime.assert_not_called()

    class _TwoTicksThenExitProc:
        def __init__(self, stdout_text):
            self.stdout = _FakeStdout(stdout_text)
            self.stdin = MagicMock()
            self._polls = 0

        def poll(self):
            self._polls += 1
            return None if self._polls <= 2 else 0

        def wait(self):
            return 0

        def terminate(self):
            pass

    def test_the_session_id_is_recorded_exactly_once(self):
        stdout_text = (
            '{"type":"system","subtype":"init","session_id":"sess-49d8ac0f-6398"}\n'
            '{"type":"result"}\n'
        )
        proc = self._TwoTicksThenExitProc(stdout_text)

        def popen(cmd, cwd, **kwargs):
            return proc

        recorded = []
        with patch("lightcycle.adapters.worker_session.subprocess.Popen", popen):
            run("/data/root", "/work/item-1", "coder", "opus", "sys", 5,
                record_session_id=recorded.append, open_step=_open)
        self.assertEqual(recorded, ["sess-49d8ac0f-6398"])


class TestDispatchEvent(unittest.TestCase):
    def test_rejected_rate_limit_line_forwards_to_policy_and_closes(self):
        policy = SessionPolicy()
        events = queue.Queue()
        dispatch_event(json.loads(REJECTED_LINE), REJECTED_LINE, events)
        drain(events, policy)
        self.assertEqual(policy.on_result(has_open_step=True), CLOSE)

    def test_an_assistant_command_line_queues_nothing(self):
        events = queue.Queue()
        line = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "input": {"command": "lc done abc.1 done"}}]}})
        dispatch_event(json.loads(line), line, events)
        self.assertEqual(events.qsize(), 0)

    def test_result_line_queues_a_result_event(self):
        events = queue.Queue()
        line = '{"type":"result"}'
        dispatch_event(json.loads(line), line, events)
        self.assertEqual(events.get_nowait(), (RESULT, None))

    def test_dispatch_never_touches_the_policy(self):
        events = queue.Queue()
        line = '{"type":"result"}'
        dispatch_event(json.loads(line), line, events)
        dispatch_event(json.loads(REJECTED_LINE), REJECTED_LINE, events)
        self.assertEqual(events.qsize(), 2)

    def test_system_init_line_queues_a_session_id_event(self):
        events = queue.Queue()
        line = '{"type":"system","subtype":"init","session_id":"sess-abc"}'
        dispatch_event(json.loads(line), line, events)
        self.assertEqual(events.get_nowait(), (SESSION_ID, "sess-abc"))

    def test_non_init_system_line_queues_nothing(self):
        events = queue.Queue()
        line = '{"type":"system","subtype":"hook_started","session_id":"sess-abc"}'
        dispatch_event(json.loads(line), line, events)
        self.assertEqual(events.qsize(), 0)

    def test_system_init_line_drains_into_the_policy(self):
        policy = SessionPolicy()
        events = queue.Queue()
        line = '{"type":"system","subtype":"init","session_id":"sess-abc"}'
        dispatch_event(json.loads(line), line, events)
        drain(events, policy)
        self.assertEqual(policy.session_id, "sess-abc")


class TestHasOpenStep(unittest.TestCase):
    def _store(self, *claimed):
        store = MagicMock()
        store.claimed_steps.return_value = [
            types.SimpleNamespace(claimed_by=c) for c in claimed]
        return store

    def test_true_while_a_step_is_claimed_by_this_spawn(self):
        self.assertTrue(has_open_step(self._store("other", "spawn1"), "spawn1"))

    def test_false_once_no_step_is_claimed_by_this_spawn(self):
        self.assertFalse(has_open_step(self._store("other"), "spawn1"))

    def test_true_not_false_when_the_store_cannot_be_read(self):
        store = MagicMock()
        store.claimed_steps.side_effect = sqlite3.OperationalError("locked")
        self.assertTrue(has_open_step(store, "spawn1"))


if __name__ == "__main__":
    unittest.main()


class TestSessionPolicyHasOneWriter(unittest.TestCase):
    def _fn(self, name):
        src = pathlib.Path(worker_session_mod.__file__).read_text()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError("no function %r" % name)

    def test_the_reader_thread_entry_takes_no_policy(self):
        args = [a.arg for a in self._fn("dispatch_event").args.args]
        self.assertNotIn("policy", args)

    def test_the_reader_closure_never_names_the_policy(self):
        reader = self._fn("reader")
        named = {n.id for n in ast.walk(reader) if isinstance(n, ast.Name)}
        self.assertNotIn("policy", named)

    READER_THREAD_FUNCTIONS = ("dispatch_event", "reader")

    def test_no_policy_mutation_sits_on_the_reader_thread(self):
        src = pathlib.Path(worker_session_mod.__file__).read_text()
        callers = set()
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.FunctionDef):
                continue
            for child in ast.walk(node):
                if (isinstance(child, ast.Attribute)
                        and isinstance(child.value, ast.Name)
                        and child.value.id == "policy"
                        and child.attr.startswith("observe_")):
                    callers.add(node.name)
        self.assertEqual(callers, {"drain"})
        self.assertEqual(callers.intersection(self.READER_THREAD_FUNCTIONS), set())
