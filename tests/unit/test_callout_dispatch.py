import json
import unittest

from lightcycle.application.work.step_detail import StepDetail
from lightcycle.domain.work import State
from lightcycle.ports.github import StackLayer
from lightcycle.ports.script_runner import ScriptResult
from tests.support.callout_rig import CalloutRig, callout, ok
from tests.support.fake_script_runner import FakeScriptRunner


class TestWhichGatesStart(unittest.TestCase):
    def test_only_the_callout_keyed_on_the_gates_subject_starts(self):
        rig = CalloutRig([callout("a", "pr"), callout("b", "description")], presents="pr")
        step = rig.gate()

        rig.use_case.execute(100)

        self.assertEqual([c["key"] for c in rig.runner.started], [rig.key(step, "a")])

    def test_the_stdin_carries_protocol_two_and_the_pr_subject_with_its_stack(self):
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

        request = rig.stdin()
        self.assertEqual(request["protocol"], 2)
        self.assertEqual(request["verb"], "run")
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

        self.assertEqual(len(rig.runner.started), 1)
        self.assertIn("stack_error", rig.stdin()["subject"])
        self.assertNotIn("stack_layers", rig.stdin()["subject"])

    def test_a_description_gate_gets_the_description_subject(self):
        rig = CalloutRig([callout("a", "description")], presents="description")
        rig.gate()

        rig.use_case.execute(100)

        self.assertEqual(
            rig.stdin()["subject"], {"kind": "description", "value": "the description"})

    def test_an_artifact_gate_gets_the_named_artifact(self):
        rig = CalloutRig([callout("a", "artifact:spec")], presents="artifact:spec")
        step = rig.gate()
        rig.store.add_artifact(rig.store.get_node(step).item, "spec", "specs/s.md")

        rig.use_case.execute(100)

        self.assertEqual(
            rig.stdin()["subject"], {"kind": "artifact", "name": "spec", "value": "specs/s.md"})

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
        rig.runner.finish(rig.key(step), ScriptResult(exit_code=1))
        rig.use_case.execute(101)
        self.assertEqual(rig.records(step)["a"]["status"], "failed")

        rig.use_case.execute(102)

        self.assertEqual(len(rig.runner.started), 1)


class TestFailures(unittest.TestCase):
    def _fails(self, result):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.runner.finish(rig.key(step), result)

        rig.use_case.execute(101)

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
        rig.runner.orphan_running()

        rig.use_case.execute(101)
        rig.use_case.execute(102)

        self.assertEqual(rig.records(step)["a"]["status"], "failed")
        self.assertEqual(rig.records(step)["a"]["message"], "interrupted by a pool restart")
        self.assertEqual(len(rig.runner.started), 1)

    def test_a_run_polled_to_a_result_on_the_reaping_tick_is_ok(self):
        rig = CalloutRig([callout("a", "pr", timeout=30)])
        step = rig.gate()
        rig.use_case.execute(100)
        self.assertEqual(rig.records(step)["a"]["deadline"], 130)
        rig.runner.finish(rig.key(step), ok(("View", "link", "myapp://open?x=1")))

        rig.use_case.execute(130)

        self.assertEqual(rig.records(step)["a"]["status"], "ok")

    def test_one_failure_leaves_the_other_callouts_rows_in_the_detail(self):
        rig = CalloutRig([callout("a", "pr"), callout("b", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        rig.runner.finish(rig.key(step, "a"), ok(("One", "link", "myapp://1"), ("Two", "text", "t")))
        rig.runner.finish(rig.key(step, "b"), ScriptResult(exit_code=2))

        rig.use_case.execute(101)

        run = type("R", (), {"pr": None, "branch": None, "pass_id": None, "phase": None, "item": None})()
        entries, _ = StepDetail(rig.store, _DetailFlow()).resolve(
            rig.store.get_node(step), {}, [], run=run)
        rows = [(e.key, e.value) for e in entries if e.kind == "callout"]
        self.assertEqual(rows, [
            ("callout:a:1", "myapp://1"), ("callout:a:2", "t"),
            ("callout:b", "failed: exited with code 2")])

    def test_a_run_that_fails_with_only_errors_keeps_them(self):
        rig = CalloutRig([callout("a", "pr")])
        step = rig.gate()
        rig.use_case.execute(100)
        stdout = json.dumps({"status": "failed", "errors": [{"message": "m", "fix": "f"}]})
        rig.runner.finish(rig.key(step), ScriptResult(exit_code=0, stdout=stdout))

        rig.use_case.execute(101)

        record = rig.records(step)["a"]
        self.assertEqual((record["status"], record["message"]), ("failed", "m"))
        self.assertEqual(record["errors"], [{"message": "m", "fix": "f"}])


class _DetailFlow:
    def flow_for(self, node):
        from lightcycle.domain.flow.flow import Flow
        from lightcycle.domain.flow.step_def import StepDef
        return Flow({"gate": StepDef(presents="pr", phase="code")})

    def phase_for(self, node):
        return None
