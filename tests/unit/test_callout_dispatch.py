import json
import unittest

from lightcycle.application.work.step_detail import StepDetail
from lightcycle.domain.work import State
from lightcycle.ports.github import StackLayer
from lightcycle.ports.script_runner import ScriptResult
from tests.support.callout_rig import CalloutRig, callout, ok, preflight_failed, preflight_ok
from tests.support.fake_script_runner import FakeScriptRunner


class TestWhichGatesStart(unittest.TestCase):
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
