import datetime
import json
import time
import unittest

from lightcycle.application.work.step_detail import StepDetail
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.domain.work import State
from lightcycle.ports.github import StackLayer
from lightcycle.ports.script_runner import ScriptResult
from tests.support.callout_rig import (
    CalloutRig,
    callout,
    ok,
    preflight_failed,
    preflight_ok,
    with_usage,
)
from tests.support.fake_script_runner import FakeScriptRunner


TWO_PHASES = {
    "spec-write": StepDef(phase="spec", principal_output="spec"),
    "spec-gate": StepDef(presents="pr", phase="spec"),
    "code-write": StepDef(phase="code", principal_output="code"),
    "code-gate": StepDef(presents="pr", phase="code"),
}


def two_phase_rig(callouts):
    rig = CalloutRig(callouts, defs=TWO_PHASES)
    return rig, rig.gate(stage="spec-gate"), rig.gate(stage="code-gate")


class TestWhichGatesStart(unittest.TestCase):
    def test_a_callout_runs_only_at_the_gate_whose_principal_output_it_lists(self):
        rig, spec_gate, code_gate = two_phase_rig([
            callout("a", principal_outputs=("spec",)),
            callout("b", principal_outputs=("code",))])

        rig.use_case.execute(100)

        self.assertEqual(
            sorted(c["key"] for c in rig.runner.started),
            sorted([rig.preflight_key(spec_gate, "a"), rig.preflight_key(code_gate, "b")]))

    def test_the_request_step_carries_the_principal_output(self):
        rig, spec_gate, _code_gate = two_phase_rig([callout("a", principal_outputs=("spec",))])

        rig.use_case.execute(100)
        preflight = rig.stdin(0)
        rig.pass_preflight(spec_gate, 101)
        run = rig.stdin(1)

        self.assertEqual(preflight["context"], "gate")
        self.assertEqual(preflight["step"]["principal_output"], "spec")
        self.assertEqual(run["verb"], "run")
        self.assertEqual(run["step"]["principal_output"], "spec")

    def test_a_callout_listing_several_outputs_runs_at_each(self):
        rig, spec_gate, code_gate = two_phase_rig([
            callout("a", principal_outputs=("spec", "code"))])

        rig.use_case.execute(100)

        self.assertEqual(
            sorted(c["key"] for c in rig.runner.started),
            sorted([rig.preflight_key(spec_gate, "a"), rig.preflight_key(code_gate, "a")]))

    def test_a_gate_with_no_resolvable_principal_output_starts_nothing(self):
        defs = {
            "x-write": StepDef(phase="mixed", principal_output="spec"),
            "y-write": StepDef(phase="mixed", principal_output="code"),
            "mixed-gate": StepDef(presents="pr", phase="mixed"),
            "bare-gate": StepDef(presents="pr", phase="bare"),
        }
        rig = CalloutRig([callout("a", principal_outputs=("spec", "code"))], defs=defs)
        rig.gate(stage="mixed-gate")
        rig.gate(stage="bare-gate")

        rig.use_case.execute(100)

        self.assertEqual(rig.runner.started, [])

    def test_a_matching_subject_with_a_non_matching_principal_output_starts_nothing(self):
        rig = CalloutRig([callout("a", "pr", principal_outputs=("spec",))])
        rig.gate()

        rig.use_case.execute(100)

        self.assertEqual(rig.runner.started, [])

    def test_only_the_callout_keyed_on_the_gates_subject_starts(self):
        rig = CalloutRig([callout("a", "pr"), callout("b", "description")], presents="pr")
        step = rig.gate()

        rig.use_case.execute(100)

        self.assertEqual([c["key"] for c in rig.runner.started], [rig.preflight_key(step, "a")])

    def test_the_stdin_carries_protocol_one_and_the_pr_subject_with_its_stack(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        item = rig.store.get_node(step).item
        pid = rig.store.open_pass(item)
        rid = rig.store.open_run(item, pid, "code")
        rig.store.set_pr(rid, "https://github.com/o/r/pull/7")
        rig.store.set_stack(rid, "https://github.com/o/r/stack/1")
        layer = StackLayer(7, "https://github.com/o/r/pull/7", "feat", "main", "abc", "OPEN")
        rig.github.script_stack("https://github.com/o/r/stack/1", [layer])

        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)

        request = rig.stdin(1)
        self.assertEqual(request["protocol"], 2)
        self.assertEqual(request["callout"], "a")
        self.assertEqual(request["step"]["id"], step)
        self.assertEqual(request["subject"]["kind"], "pr")
        self.assertEqual(request["subject"]["url"], "https://github.com/o/r/pull/7")
        self.assertEqual(request["subject"]["stack_layers"][0]["head_ref"], "feat")
        self.assertIn("workspace", request["repos"])

    def test_a_stack_read_failure_gives_stack_error_and_the_callout_still_starts(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        item = rig.store.get_node(step).item
        rid = rig.store.open_run(item, rig.store.open_pass(item), "code")
        rig.store.set_pr(rid, "https://github.com/o/r/pull/7")
        rig.store.set_stack(rid, "https://github.com/o/r/stack/1")
        rig.github.script_stack("https://github.com/o/r/stack/1", [])
        rig.github._failing_calls = {"stack_view"}

        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)

        self.assertEqual(len(rig.runner.started), 2)
        self.assertIn("stack_error", rig.stdin(1)["subject"])
        self.assertNotIn("stack_layers", rig.stdin(1)["subject"])

    def test_a_description_gate_gets_the_description_subject(self):
        rig = CalloutRig([callout("a", "description")], presents="description")
        step = rig.gate()

        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)

        self.assertEqual(
            rig.stdin(1)["subject"], {"kind": "description", "value": "the description"})

    def test_an_artifact_gate_gets_the_named_artifact(self):
        rig = CalloutRig([callout("a", "artifact:spec")], presents="artifact:spec")
        step = rig.gate()
        rig.store.add_artifact(rig.store.get_node(step).item, "spec", "specs/s.md")

        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)

        self.assertEqual(
            rig.stdin(1)["subject"], {"kind": "artifact", "name": "spec", "value": "specs/s.md"})

    def test_a_gate_with_no_presents_a_done_step_and_an_agent_step_start_nothing(self):
        none_rig = CalloutRig([callout("a", "pr")], presents=None)
        none_rig.gate()
        running = CalloutRig([callout("a", "pr")])
        running.gate(state=State.DONE)
        agent = CalloutRig([callout("a", "pr")])
        agent.gate(role="agent")

        for rig in (none_rig, running, agent):
            rig.use_case.execute(100)
            self.assertEqual(rig.runner.started, [])

    def test_a_second_tick_does_not_start_it_again(self):
        rig = CalloutRig([callout("a", "pr")])
        rig.gate()

        rig.use_case.execute(100)
        rig.use_case.execute(101)

        self.assertEqual(len(rig.runner.started), 1)

    def test_a_failed_record_is_not_restarted(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.runner.finish(rig.preflight_key(step), ScriptResult(exit_code=1))
        rig.use_case.execute(101)
        self.assertEqual(rig.records(step)["a"]["status"], "failed")

        rig.use_case.execute(102)

        self.assertEqual(len(rig.runner.started), 1)


class TestUnreturnedRun(unittest.TestCase):
    def _running(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)
        return rig, step

    def test_a_record_the_runner_never_returns_is_failed_past_its_deadline_grace(self):
        rig, step = self._running()
        deadline = rig.records(step)["a"]["deadline"]

        rig.use_case.execute(deadline + 60)

        self.assertEqual(rig.records(step)["a"]["status"], "running")
        self.assertEqual(rig.runner.running(), [rig.key(step)])

        rig.use_case.execute(deadline + 61)

        record = rig.records(step)["a"]
        self.assertEqual(record["status"], "failed")
        self.assertIn("still running 60s past its deadline", record["message"])
        self.assertEqual(rig.runner.running(), [])

    def test_a_running_record_with_no_deadline_is_left_alone(self):
        rig, step = self._running()
        record = rig.records(step)["a"]
        del record["deadline"]
        rig.store.replace_artifact(
            step, "callout-runs", json.dumps({"a": record}), internal=True)

        rig.use_case.execute(10**6)

        self.assertEqual(rig.records(step)["a"]["status"], "running")

    def test_sleeps_covering_the_grace_do_not_fail_the_record(self):
        rig, step = self._running()
        deadline = rig.records(step)["a"]["deadline"]

        rig.use_case.execute(deadline + 500, sleeps=[(deadline, deadline + 500)])

        self.assertEqual(rig.records(step)["a"]["status"], "running")


class TestFailures(unittest.TestCase):
    def _fails(self, result):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)
        rig.runner.finish(rig.key(step), result)

        rig.use_case.execute(102)

        node = rig.store.get_node(step)
        self.assertEqual(node.state, State.WAITING)
        self.assertIsNone(node.outcome)
        self.assertFalse(node.park.reason or node.park.needs)
        self.assertEqual(rig.records(step)["a"]["status"], "failed")
        notes = [n for n in (node.notes or "").splitlines() if n.startswith("callout:a: failed")]
        self.assertEqual(len(notes), 1)
        return rig.records(step)["a"]

    def test_a_non_zero_exit_fails_the_callout(self):
        self.assertIn("code 3", self._fails(ScriptResult(exit_code=3))["message"])

    def test_a_timeout_fails_the_callout(self):
        self.assertIn("timed out", self._fails(ScriptResult(exit_code=None, timed_out=True))["message"])

    def test_invalid_stdout_fails_the_callout(self):
        record = self._fails(ScriptResult(exit_code=0, stdout="nope"))
        self.assertIn("invalid response", record["message"])

    def test_an_answer_of_failed_fails_the_callout_with_its_message(self):
        stdout = json.dumps({"status": "failed", "message": "no luck"})
        self.assertEqual(self._fails(ScriptResult(exit_code=0, stdout=stdout))["message"], "no luck")

    def test_a_runner_that_raises_on_start_gives_a_failed_record_and_no_exception(self):
        class Raising(FakeScriptRunner):
            def start(self, *a, **k):
                raise OSError("no such file")

        rig = CalloutRig([callout("a", "pr")], runner=Raising())
        step = rig.gate()

        rig.use_case.execute(100)

        self.assertEqual(rig.records(step)["a"]["status"], "failed")
        self.assertIn("no such file", rig.records(step)["a"]["message"])

    def test_a_pool_restart_marks_the_run_interrupted_and_never_reruns_it(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)
        rig.runner.orphan_running()

        rig.use_case.execute(102)
        rig.use_case.execute(103)

        self.assertEqual(rig.records(step)["a"]["status"], "failed")
        self.assertEqual(rig.records(step)["a"]["message"], "interrupted by a pool restart")
        self.assertEqual(len(rig.runner.started), 2)

    def test_a_run_polled_to_a_result_on_the_reaping_tick_is_ok(self):
        rig = CalloutRig([callout("a", "pr", timeout=30)])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 110)
        self.assertEqual(rig.records(step)["a"]["deadline"], 140)
        rig.runner.finish(rig.key(step), ok(("View", "link", "myapp://open?x=1")))

        rig.use_case.execute(140)

        self.assertEqual(rig.records(step)["a"]["status"], "ok")

    def test_one_failure_leaves_the_other_callouts_rows_in_the_detail(self):
        rig = CalloutRig([callout("a", "pr"), callout("b", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101, "a", "b")
        rig.runner.finish(rig.key(step, "a"), ok(("One", "link", "myapp://1"), ("Two", "text", "t")))
        rig.runner.finish(rig.key(step, "b"), ScriptResult(exit_code=2))

        rig.use_case.execute(102)

        run = type("R", (), {"pr": None, "branch": None, "pass_id": None, "phase": None, "item": None})()
        entries, _ = StepDetail(rig.store, _DetailFlow()).resolve(
            rig.store.get_node(step), {}, [], run=run)
        rows = [(e.key, e.value) for e in entries if e.kind == "callout"]
        self.assertEqual(rows, [
            ("callout:a:1", "myapp://1"), ("callout:a:2", "t"),
            ("callout:b", "failed: exited with code 2")])


class TestUsageCost(unittest.TestCase):
    def _run(self, *callout_ids):
        rig = CalloutRig([callout(c, "pr") for c in callout_ids or ("a",)])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101, *callout_ids)
        return rig, step

    def _cost(self, rig, step):
        return rig.store.get_step(step).usage_cost_usd.to_usd()

    def test_an_ok_response_with_usage_adds_cost_with_reported_basis_and_changes_nothing_else(self):
        rig, step = self._run()
        before = rig.store.get_step(step)
        self.assertEqual(before.state, State.WAITING)
        rig.runner.finish(rig.key(step), with_usage(ok(), cost_usd=0.42, model="m"))

        rig.use_case.execute(102)

        after = rig.store.get_step(step)
        self.assertEqual(after.usage_cost_usd.to_usd(), 0.42)
        self.assertEqual(after.usage_cost_basis, "reported")
        self.assertEqual(after.state, State.WAITING)
        self.assertEqual(after.outcome, before.outcome)
        self.assertEqual(after.turn_count, 0)
        self.assertEqual(after.usage_input_tokens, 0)
        self.assertEqual(rig.records(step)["a"]["cost_usd"], 0.42)
        self.assertEqual(rig.records(step)["a"]["model"], "m")

    def test_a_failed_response_with_usage_also_records_it(self):
        rig, step = self._run()
        rig.runner.finish(rig.key(step), with_usage(ok(), status="failed", cost_usd=0.1))

        rig.use_case.execute(102)

        self.assertEqual(rig.records(step)["a"]["status"], "failed")
        self.assertEqual(self._cost(rig, step), 0.1)
        self.assertEqual(rig.records(step)["a"]["cost_usd"], 0.1)

    def test_exit_timeout_and_invalid_output_record_nothing(self):
        results = [
            ScriptResult(exit_code=2),
            ScriptResult(exit_code=None, timed_out=True),
            ScriptResult(exit_code=0, stdout='{"status": "ok", "usage": {"cost_usd": -1}}'),
        ]
        for result in results:
            with self.subTest(result=result):
                rig, step = self._run()
                rig.runner.finish(rig.key(step), result)

                rig.use_case.execute(102)

                self.assertEqual(self._cost(rig, step), 0)
                self.assertIsNone(rig.store.get_step(step).usage_cost_basis)
                self.assertNotIn("cost_usd", rig.records(step)["a"])

    def test_an_ok_response_without_usage_records_nothing(self):
        rig, step = self._run()
        rig.runner.finish(rig.key(step), ok())

        rig.use_case.execute(102)

        self.assertEqual(self._cost(rig, step), 0)
        self.assertNotIn("cost_usd", rig.records(step)["a"])

    def test_several_callouts_on_one_gate_sum_and_keep_their_own_figures(self):
        rig, step = self._run("a", "b", "c")
        rig.runner.finish(rig.key(step, "a"), with_usage(ok(), cost_usd=0.4))
        rig.runner.finish(rig.key(step, "b"), with_usage(ok(), status="failed", cost_usd=0.1))
        rig.runner.finish(rig.key(step, "c"), ScriptResult(exit_code=0, stdout=json.dumps(
            {"status": "failed", "message": "no"})))

        rig.use_case.execute(102)

        records = rig.records(step)
        self.assertAlmostEqual(self._cost(rig, step), 0.5)
        self.assertEqual(records["a"]["cost_usd"], 0.4)
        self.assertEqual(records["b"]["cost_usd"], 0.1)
        self.assertNotIn("cost_usd", records["c"])

    def test_a_cost_that_rounds_to_zero_is_not_written_but_stays_on_the_record(self):
        rig, step = self._run()
        rig.runner.finish(rig.key(step), with_usage(ok(), cost_usd=0.0000001))

        rig.use_case.execute(102)

        self.assertEqual(self._cost(rig, step), 0)
        self.assertIsNone(rig.store.get_step(step).usage_cost_basis)
        self.assertEqual(rig.records(step)["a"]["cost_usd"], 0.0000001)

    def test_a_second_tick_does_not_add_the_cost_again(self):
        rig, step = self._run()
        rig.runner.finish(rig.key(step), with_usage(ok(), cost_usd=0.42))

        rig.use_case.execute(102)
        rig.use_case.execute(103)

        self.assertEqual(self._cost(rig, step), 0.42)

    def test_a_run_interrupted_by_a_restart_records_no_cost(self):
        rig, step = self._run()
        rig.runner.orphan_running()

        rig.use_case.execute(102)

        self.assertEqual(self._cost(rig, step), 0)
        self.assertNotIn("cost_usd", rig.records(step)["a"])


class TestPreflight(unittest.TestCase):
    def _detail_rows(self, rig, step):
        run = type("R", (), {"pr": None, "branch": None, "pass_id": None, "phase": None, "item": None})()
        entries, _ = StepDetail(rig.store, _DetailFlow()).resolve(
            rig.store.get_node(step), {}, [], run=run)
        return [(e.key, e.value) for e in entries if e.kind == "callout"]

    def test_a_gate_starts_only_the_preflight_with_verb_context_and_no_subject(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()

        rig.use_case.execute(100)

        self.assertEqual(len(rig.runner.started), 1)
        request = rig.stdin()
        self.assertEqual(request["verb"], "preflight")
        self.assertEqual(request["context"], "gate")
        self.assertEqual(request["protocol"], 2)
        self.assertNotIn("subject", request)
        self.assertEqual(rig.records(step)["a"]["phase"], "preflight")

    def test_a_passing_preflight_starts_the_run_in_the_same_reap_and_resets_the_deadline(self):
        rig = CalloutRig([callout("a", "pr", timeout=60)])
        step = rig.gate()
        rig.use_case.execute(100)
        self.assertEqual(rig.records(step)["a"]["deadline"], 130)

        rig.pass_preflight(step, 110)

        self.assertEqual(len(rig.runner.started), 2)
        self.assertEqual(rig.stdin(1)["verb"], "run")
        self.assertEqual(rig.stdin(1)["subject"]["kind"], "pr")
        self.assertNotIn("context", rig.stdin(1))
        record = rig.records(step)["a"]
        self.assertEqual((record["phase"], record["deadline"], record["status"]), ("run", 170, "running"))

    def test_a_failed_preflight_skips_the_run_keeps_the_errors_and_is_never_retried(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.runner.finish(
            rig.preflight_key(step), preflight_failed(("no pandoc", "brew install pandoc"), ("b", "fix b")))

        rig.use_case.execute(101)
        rig.use_case.execute(102)

        node = rig.store.get_node(step)
        self.assertEqual(node.state, State.WAITING)
        record = rig.records(step)["a"]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["message"], "no pandoc (and 1 more)")
        self.assertEqual(record["errors"][0], {"message": "no pandoc", "fix": "brew install pandoc"})
        self.assertEqual(len(record["errors"]), 2)
        self.assertEqual(len(rig.runner.started), 1)
        notes = [n for n in (node.notes or "").splitlines() if n.startswith("callout:a: failed")]
        self.assertEqual(len(notes), 1)

    def test_engine_detected_preflight_failures_carry_the_verb_fix(self):
        for result in (
            ScriptResult(exit_code=1), ScriptResult(exit_code=None, timed_out=True),
            ScriptResult(exit_code=0, stdout="nope"),
        ):
            rig = CalloutRig([callout("a", "pr")])
            step = rig.gate()
            rig.use_case.execute(100)
            rig.runner.finish(rig.preflight_key(step), result)

            rig.use_case.execute(101)

            record = rig.records(step)["a"]
            self.assertEqual(record["status"], "failed")
            self.assertTrue(record["message"].startswith("preflight: "))
            self.assertIn('verb "preflight"', record["errors"][0]["fix"])
            self.assertEqual(len(rig.runner.started), 1)

    def test_a_run_that_fails_with_only_errors_keeps_them(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)
        stdout = json.dumps({"status": "failed", "errors": [{"message": "m", "fix": "f"}]})
        rig.runner.finish(rig.key(step), ScriptResult(exit_code=0, stdout=stdout))

        rig.use_case.execute(102)

        record = rig.records(step)["a"]
        self.assertEqual((record["status"], record["message"]), ("failed", "m"))
        self.assertEqual(record["errors"], [{"message": "m", "fix": "f"}])

    def test_a_record_with_no_phase_is_reaped_as_a_run(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)
        runs = rig.records(step)
        del runs["a"]["phase"]
        rig.use_case._write(step, runs)
        rig.runner.finish(rig.key(step), ok(("View", "link", "myapp://x")))

        rig.use_case.execute(102)

        self.assertEqual(rig.records(step)["a"]["status"], "ok")

    def test_a_preflight_result_on_its_deadline_tick_is_reaped_not_interrupted(self):
        rig = CalloutRig([callout("a", "pr", timeout=60)])
        step = rig.gate()
        rig.use_case.execute(100)

        rig.pass_preflight(step, 130)

        self.assertEqual(rig.records(step)["a"]["phase"], "run")

    def test_a_short_callout_timeout_caps_the_preflight_deadline_and_runner_timeout(self):
        rig = CalloutRig([callout("a", "pr", timeout=10)])
        step = rig.gate()

        rig.use_case.execute(100)

        self.assertEqual(rig.records(step)["a"]["deadline"], 110)
        self.assertEqual(rig.runner.started[0]["timeout"], 10)

    def test_mixed_callouts_show_artifacts_and_the_failed_row_with_its_error_in_order(self):
        rig = CalloutRig([callout("a", "pr"), callout("b", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.runner.finish(rig.preflight_key(step, "a"), preflight_ok())
        rig.runner.finish(rig.preflight_key(step, "b"), preflight_failed(("bad", "do x")))
        rig.use_case.execute(101)
        rig.runner.finish(rig.key(step, "a"), ok(("One", "link", "myapp://1"), ("Two", "text", "t")))
        rig.use_case.execute(102)

        self.assertEqual(self._detail_rows(rig, step), [
            ("callout:a:1", "myapp://1"), ("callout:a:2", "t"),
            ("callout:b", "failed: bad"), ("callout:b:error:1", "bad - fix: do x")])


class TestFinished(unittest.TestCase):
    def test_a_running_record_has_no_finished(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()

        rig.use_case.execute(100)

        self.assertNotIn("finished", rig.records(step)["a"])

    def test_an_ok_record_carries_the_tick_time(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 105)
        rig.runner.finish(rig.key(step), ok(("View", "link", "myapp://1")))

        rig.use_case.execute(117)

        self.assertEqual(rig.records(step)["a"]["finished"], 117)

    def test_a_failed_record_carries_the_tick_time(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 105)
        rig.runner.finish(rig.key(step), ScriptResult(exit_code=3))

        rig.use_case.execute(121)

        self.assertEqual(rig.records(step)["a"]["finished"], 121)

    def test_a_failed_preflight_record_carries_the_tick_time(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.runner.finish(rig.preflight_key(step), preflight_failed(("bad", "fix")))

        rig.use_case.execute(125)

        self.assertEqual(rig.records(step)["a"]["finished"], 125)

    def test_an_interrupted_record_carries_the_tick_time(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.runner.orphan_running()

        rig.use_case.execute(133)

        self.assertEqual(rig.records(step)["a"]["finished"], 133)

    def test_a_start_time_failure_carries_the_tick_time(self):
        class Raising(FakeScriptRunner):
            def start(self, *a, **k):
                raise OSError("no such file")

        rig = CalloutRig([callout("a", "pr")], runner=Raising())
        step = rig.gate()

        rig.use_case.execute(140)

        self.assertEqual(rig.records(step)["a"]["finished"], 140)


class _DetailFlow:
    def flow_for(self, node):
        from lightcycle.domain.flow.flow import Flow
        from lightcycle.domain.flow.step_def import StepDef
        return Flow({"gate": StepDef(presents="pr", phase="code")})

    def phase_for(self, node):
        return None


class TestSuspendRetry(unittest.TestCase):
    TIMED_OUT = ScriptResult(exit_code=None, timed_out=True, started_at=100.0, finished_at=500.0)
    ACROSS = ((200.0, 400.0),)

    def _run_phase(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)
        return rig, step

    def test_a_run_timeout_across_a_suspend_restarts_once(self):
        rig, step = self._run_phase()
        started = len(rig.runner.started)
        rig.runner.finish(rig.key(step), self.TIMED_OUT)

        rig.use_case.execute(102, self.ACROSS)

        record = rig.records(step)["a"]
        self.assertEqual(record["status"], "running")
        self.assertTrue(record["suspend_retried"])
        self.assertEqual(len(rig.runner.started), started + 1)
        self.assertEqual(rig.stdin(started)["verb"], "run")

    def test_a_preflight_timeout_across_a_suspend_restarts_once(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.runner.finish(rig.preflight_key(step), self.TIMED_OUT)

        rig.use_case.execute(102, self.ACROSS)

        record = rig.records(step)["a"]
        self.assertEqual((record["status"], record["phase"]), ("running", "preflight"))
        self.assertTrue(record["suspend_retried"])
        self.assertEqual(len(rig.runner.started), 2)
        self.assertEqual(rig.stdin(1)["verb"], "preflight")

    def test_a_second_callout_timeout_fails(self):
        rig, step = self._run_phase()
        rig.runner.finish(rig.key(step), self.TIMED_OUT)
        rig.use_case.execute(102, self.ACROSS)
        rig.runner.finish(rig.key(step), self.TIMED_OUT)

        rig.use_case.execute(103, self.ACROSS)

        record = rig.records(step)["a"]
        self.assertEqual(record["status"], "failed")
        self.assertIn("timed out", record["message"])

    def test_a_timeout_with_no_suspend_fails_at_once(self):
        rig, step = self._run_phase()
        rig.runner.finish(rig.key(step), self.TIMED_OUT)

        rig.use_case.execute(102)

        self.assertEqual(rig.records(step)["a"]["status"], "failed")



def closed_gate(rig):
    step = rig.gate()
    rig.use_case.execute(100)
    rig.pass_preflight(step, 101)
    return step


def finish_run(rig, step, callout_id="a", result=None):
    rig.runner.finish(rig.key(step, callout_id), result or ok())
    rig.use_case.execute(102)


def close(rig, step, outcome="approved"):
    rig.store.complete_node(step, outcome)


def cleanup_key(step, callout_id="a"):
    return "callout:%s:%s:cleanup" % (step, callout_id)


def cleanup_stdins(rig):
    return [
        json.loads(c["stdin"]) for c in rig.runner.started if c["key"].endswith(":cleanup")]


def set_closed_at(rig, step, seconds_ago):
    when = datetime.datetime.fromtimestamp(time.time() - seconds_ago, datetime.timezone.utc)
    rig.store._get(step)["closed_at"] = when.isoformat()


class TestCleanupRequest(unittest.TestCase):
    def test_a_closed_gate_gets_one_cleanup_with_the_stored_subject_and_outcome(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        item = rig.store.get_node(step).item
        rid = rig.store.open_run(item, rig.store.open_pass(item), "code")
        rig.store.set_pr(rid, "https://github.com/o/r/pull/7")
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101)
        run_request = rig.stdin(1)
        finish_run(rig, step)
        rig.store.close_run(rid)
        close(rig, step, "approved")

        response = rig.use_case.execute(time.time())

        self.assertEqual(response.cleanups, [cleanup_key(step)])
        request = cleanup_stdins(rig)[0]
        self.assertEqual(request["verb"], "cleanup")
        self.assertEqual(request["outcome"], "approved")
        self.assertEqual(request["subject"]["url"], "https://github.com/o/r/pull/7")
        self.assertEqual(request["subject"], run_request["subject"])
        self.assertEqual(request["item"], run_request["item"])
        self.assertEqual(request["step"], run_request["step"])
        self.assertNotIn("context", request)
        self.assertIsNone(request["repos"]["workspace"])
        self.assertEqual(len(rig.runner.started), 3)

    def test_the_record_carries_the_run_subject_and_a_running_cleanup(self):
        rig = CalloutRig([callout("a", "pr")])
        step = closed_gate(rig)
        self.assertEqual(rig.records(step)["a"]["subject"], rig.stdin(1)["subject"])
        finish_run(rig, step)
        close(rig, step, "approved")

        rig.use_case.execute(time.time())

        cleanup = rig.records(step)["a"]["cleanup"]
        self.assertEqual(cleanup["status"], "running")
        self.assertEqual(cleanup["outcome"], "approved")


class TestCleanupEligibility(unittest.TestCase):
    def _ready(self, result=None):
        rig = CalloutRig([callout("a", "pr")])
        step = closed_gate(rig)
        finish_run(rig, step, result=result)
        return rig, step

    def test_an_open_gate_gets_none(self):
        rig, step = self._ready()

        rig.use_case.execute(time.time())

        self.assertEqual(cleanup_stdins(rig), [])

    def test_a_failed_run_record_gets_one(self):
        rig, step = self._ready(ScriptResult(exit_code=1))
        close(rig, step)

        rig.use_case.execute(time.time())

        self.assertEqual(len(cleanup_stdins(rig)), 1)

    def test_a_failed_preflight_record_gets_none(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.runner.finish(rig.preflight_key(step), ScriptResult(exit_code=1))
        rig.use_case.execute(101)
        close(rig, step)

        rig.use_case.execute(time.time())

        self.assertEqual(cleanup_stdins(rig), [])

    def test_a_record_with_no_subject_gets_none(self):
        rig, step = self._ready()
        records = rig.records(step)
        del records["a"]["subject"]
        rig.store.replace_artifact(step, "callout-runs", json.dumps(records), internal=True)
        close(rig, step)

        rig.use_case.execute(time.time())

        self.assertEqual(cleanup_stdins(rig), [])

    def test_a_running_record_waits_then_gets_one(self):
        rig = CalloutRig([callout("a", "pr")])
        step = closed_gate(rig)
        records = rig.records(step)
        records["a"]["deadline"] = time.time() + 1000
        rig.store.replace_artifact(step, "callout-runs", json.dumps(records), internal=True)
        close(rig, step)

        rig.use_case.execute(time.time())
        self.assertEqual(cleanup_stdins(rig), [])

        rig.runner.finish(rig.key(step), ok())
        rig.use_case.execute(time.time())
        self.assertEqual(len(cleanup_stdins(rig)), 1)

    def test_a_gate_closed_eight_days_ago_gets_none_and_six_days_23_hours_gets_one(self):
        for ago, expected in ((8 * 86400, 0), (6 * 86400 + 23 * 3600, 1)):
            rig, step = self._ready()
            close(rig, step)
            set_closed_at(rig, step, ago)

            rig.use_case.execute(time.time())

            self.assertEqual(len(cleanup_stdins(rig)), expected, ago)

    def test_a_second_tick_does_not_start_it_again(self):
        rig, step = self._ready()
        close(rig, step)

        rig.use_case.execute(time.time())
        rig.use_case.execute(time.time())

        self.assertEqual(len(cleanup_stdins(rig)), 1)

    def test_a_cleaned_record_is_not_cleaned_again_after_it_finishes(self):
        rig, step = self._ready()
        close(rig, step)
        rig.use_case.execute(time.time())
        rig.runner.finish(cleanup_key(step), ok())
        rig.use_case.execute(time.time())

        rig.use_case.execute(time.time())

        self.assertEqual(len(cleanup_stdins(rig)), 1)

    def test_an_agent_step_gets_none(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate(role="agent")
        record = {"a": {"status": "ok", "phase": "run", "subject": {"kind": "pr"}}}
        rig.store.replace_artifact(step, "callout-runs", json.dumps(record), internal=True)
        close(rig, step)

        rig.use_case.execute(time.time())

        self.assertEqual(cleanup_stdins(rig), [])


class TestCleanupMixed(unittest.TestCase):
    def test_an_unconfigured_callout_is_recorded_failed_and_the_others_start(self):
        rig = CalloutRig([callout("a", "pr"), callout("b", "pr"), callout("c", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.pass_preflight(step, 101, "a", "b", "c")
        for cid in ("a", "b", "c"):
            rig.runner.finish(rig.key(step, cid), ok())
        rig.use_case.execute(102)
        close(rig, step)
        rig.config._callouts = [c for c in rig.config._callouts if c.id != "c"]

        rig.use_case.execute(time.time())

        self.assertEqual(
            sorted(c["callout"] for c in cleanup_stdins(rig)), ["a", "b"])
        records = rig.records(step)
        self.assertEqual(records["c"]["cleanup"]["status"], "failed")
        self.assertEqual(records["c"]["cleanup"]["message"], "callout is no longer configured")
        notes = rig.store.get_node(step).notes or ""
        self.assertEqual(notes.count("cleanup failed"), 1)
        self.assertIn("callout:c: cleanup failed", notes)


class TestCleanupReaping(unittest.TestCase):
    def _started(self, **kwargs):
        rig = CalloutRig([callout("a", "pr", **kwargs)])
        step = closed_gate(rig)
        finish_run(rig, step)
        close(rig, step, "approved")
        rig.use_case.execute(time.time())
        return rig, step

    def _assert_untouched(self, rig, step):
        node = rig.store.get_node(step)
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "approved")
        self.assertFalse(node.park.reason or node.park.needs)
        self.assertEqual(rig.records(step)["a"]["status"], "ok")

    def _fails(self, program, message, now=None):
        rig, step = self._started()
        program(rig, step)

        rig.use_case.execute(now or time.time())

        cleanup = rig.records(step)["a"]["cleanup"]
        self.assertEqual(cleanup["status"], "failed")
        self.assertIn(message, cleanup["message"])
        self.assertIn("finished", cleanup)
        notes = rig.store.get_node(step).notes or ""
        self.assertIn("callout:a: cleanup failed - ", notes)
        self.assertEqual(notes.count("cleanup failed"), 1)
        self._assert_untouched(rig, step)
        return rig, step

    def test_ok_marks_the_cleanup_ok(self):
        rig, step = self._started()
        rig.runner.finish(cleanup_key(step), ok(("x", "link", "http://x")))

        rig.use_case.execute(time.time())

        cleanup = rig.records(step)["a"]["cleanup"]
        self.assertEqual(cleanup["status"], "ok")
        self.assertIn("finished", cleanup)
        self.assertEqual(rig.records(step)["a"]["artifacts"], [])
        self._assert_untouched(rig, step)

    def test_a_failed_response(self):
        self._fails(
            lambda rig, step: rig.runner.finish(
                cleanup_key(step), with_usage(ok(), status="failed", cost_usd=0)), "boom")

    def test_a_non_zero_exit(self):
        self._fails(
            lambda rig, step: rig.runner.finish(cleanup_key(step), ScriptResult(exit_code=3)),
            "code 3")

    def test_a_timeout(self):
        self._fails(
            lambda rig, step: rig.runner.finish(
                cleanup_key(step), ScriptResult(exit_code=None, timed_out=True)),
            "timed out")

    def test_invalid_stdout(self):
        self._fails(
            lambda rig, step: rig.runner.finish(
                cleanup_key(step), ScriptResult(exit_code=0, stdout="nope")),
            "invalid response")

    def test_an_orphaned_process(self):
        self._fails(lambda rig, step: rig.runner.orphan_running(), "interrupted")

    def test_an_unreturned_process_past_the_grace(self):
        rig, step = self._started()
        deadline = rig.records(step)["a"]["cleanup"]["deadline"]
        rig.use_case.execute(deadline + 60)
        self.assertEqual(rig.records(step)["a"]["cleanup"]["status"], "running")

        rig.use_case.execute(deadline + 61)

        cleanup = rig.records(step)["a"]["cleanup"]
        self.assertEqual(cleanup["status"], "failed")
        self.assertIn("still running 60s past its deadline", cleanup["message"])
        self._assert_untouched(rig, step)

    def test_a_failed_cleanup_is_never_retried(self):
        rig, step = self._started()
        rig.runner.finish(cleanup_key(step), ScriptResult(exit_code=1))
        rig.use_case.execute(time.time())

        rig.use_case.execute(time.time())

        self.assertEqual(len(cleanup_stdins(rig)), 1)

    def test_usage_on_an_ok_cleanup_is_added_to_the_step(self):
        rig, step = self._started()
        rig.runner.finish(cleanup_key(step), with_usage(ok(), cost_usd=0.25, model="m"))

        rig.use_case.execute(time.time())

        stored = rig.store.get_step(step)
        self.assertEqual(stored.usage_cost_usd.to_usd(), 0.25)
        self.assertEqual(stored.usage_cost_basis, "reported")
        self.assertEqual(rig.records(step)["a"]["cleanup"]["status"], "ok")


class TestSubjectSnapshot(unittest.TestCase):
    def test_the_subject_is_stored_after_a_suspend_restart(self):
        rig = CalloutRig([callout("a", "pr")])
        step = closed_gate(rig)
        rig.runner.finish(
            rig.key(step), ScriptResult(exit_code=None, timed_out=True, started_at=0, finished_at=10))

        rig.use_case.execute(102, sleeps=[(2, 8)])

        record = rig.records(step)["a"]
        self.assertTrue(record["suspend_retried"])
        self.assertEqual(record["subject"], json.loads(rig.runner.started[-1]["stdin"])["subject"])
