import json
import unittest
from types import SimpleNamespace

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.park_step import ParkStepUseCase
from lightcycle.application.pool.script_stages import ScriptStageUseCase
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.domain.work import State, is_engine_step
from lightcycle.ports.script_runner import ScriptResult
from tests.support.fake_script_runner import FakeScriptRunner
from tests.support.fake_store import FakeStore
from tests.support.schedule_fakes import StubScriptLifecycle, StubWorkflowSource

PIN = "acme/build@sha1"


class StubConfig:
    def __init__(self, cap=4, timeout=300):
        self.cap = cap
        self.timeout = timeout

    def script_max_running(self):
        return self.cap

    def script_timeout_seconds(self):
        return self.timeout

    def workflow_config_block_name(self, origin, name):
        return "workflow-%s-%s" % (origin, name)


class StubFlowService:
    def __init__(self, defs):
        self._defs = defs

    def flow_for(self, node):
        return SimpleNamespace(step_def=lambda stage: self._defs.get(stage, StepDef()))

    def workflow_for(self, node):
        return PIN

    def unpinned_workflow(self, node):
        return None

    def meta_for_step(self, stage, name=None):
        return {}


class RecordingComplete:
    def __init__(self, store, fail=None, refusal=None):
        self.store = store
        self.fail = fail
        self.refusal = refusal
        self.calls = []

    def execute(self, input):
        if self.fail is not None:
            raise self.fail
        self.calls.append(input)
        self.store.update_state(input.step, State.DONE)
        return SimpleNamespace(next_step=None, teardown_refusal=self.refusal)


class Rig:
    def __init__(self, stages=None, cap=4, lifecycle=None, complete_fail=None, worktree=None,
                 ensure_error=None, refusal=None):
        self.store = FakeStore()
        self.runner = FakeScriptRunner()
        defs = stages or {
            "poll": StepDef(script="scripts/poll.sh", routes={"found": "next", "none": "poll"})}
        self.complete = RecordingComplete(self.store, complete_fail, refusal)
        self.ensured = []

        def ensure(step):
            self.ensured.append(step)
            if ensure_error:
                raise ensure_error
            return worktree

        worktrees = SimpleNamespace(ensure=ensure)
        self.gate = ScriptStageUseCase(
            self.store, StubFlowService(defs), StubConfig(cap=cap),
            StubWorkflowSource(shas={"acme": "sha1"}), lifecycle or StubScriptLifecycle(),
            self.runner, ParkStepUseCase(self.store), self.complete, worktrees)

    def step(self, stage="poll"):
        item = self.store.create_item("t", "d", workflow=PIN, shortcode="APP")
        self.store.add_artifact(item, "brief", "hello")
        return self.store.create_step(stage=stage, role="engine", item=item)

    def key(self, step):
        return "step:%s" % step


def done(outcome="found", **extra):
    payload = {"outcome": outcome}
    payload.update(extra)
    return ScriptResult(exit_code=0, stdout=json.dumps(payload))


class TestRunLog(unittest.TestCase):
    def logs(self, rig, step):
        path = rig.store.get_node(step).log_path
        return [path] if path else []

    def test_start_gets_the_label_and_the_step_records_the_returned_path(self):
        rig = Rig()
        step = rig.step()

        rig.gate.execute(0)

        self.assertEqual(rig.runner.started[0]["log_label"], "script-%s" % step)
        self.assertEqual(self.logs(rig, step), ["script-%s.log" % step])

    def test_a_clean_reap_adds_no_second_artifact(self):
        rig = Rig()
        step = rig.step()
        rig.gate.execute(0)
        rig.runner.finish(rig.key(step), done())

        rig.gate.execute(1)

        self.assertEqual(len(self.logs(rig, step)), 1)

    def test_a_parked_stage_names_the_log(self):
        rig = Rig()
        step = rig.step()
        rig.gate.execute(0)
        rig.runner.finish(rig.key(step), ScriptResult(exit_code=2, stderr_tail="bad"))

        rig.gate.execute(1)

        self.assertIn("log: script-%s.log" % step, rig.store.get_node(step).park.reason or "")


class TestTeardownRefusal(unittest.TestCase):
    def test_a_done_stage_whose_close_refuses_surfaces_the_refusal_with_its_item(self):
        rig = Rig(refusal="cannot tear down: dirty worktree")
        step = rig.step()
        item = rig.store.get_node(step).item
        rig.gate.execute(0)
        rig.runner.finish(rig.key(step), done())

        response = rig.gate.execute(1)

        self.assertEqual(response.refused, [(item, "cannot tear down: dirty worktree")])
        self.assertEqual(response.parked, [])

    def test_a_clean_close_surfaces_no_refusal(self):
        rig = Rig()
        step = rig.step()
        rig.gate.execute(0)
        rig.runner.finish(rig.key(step), done())

        self.assertEqual(rig.gate.execute(1).refused, [])


class TestReapThenStart(unittest.TestCase):
    def test_a_queued_script_step_is_started_once_and_stays_queued(self):
        rig = Rig()
        step = rig.step()

        first = rig.gate.execute(0)
        second = rig.gate.execute(1)

        self.assertEqual(first.started, [rig.key(step)])
        self.assertEqual(second.started, [])
        self.assertEqual(len(rig.runner.started), 1)
        self.assertEqual(rig.store.get_node(step).state, State.QUEUED)
        self.assertTrue(is_engine_step(rig.store.get_node(step)))

    def test_a_finished_run_completes_the_step_with_outcome_artifacts_and_note(self):
        rig = Rig()
        step = rig.step()
        rig.gate.execute(0)
        rig.runner.finish(rig.key(step), done(
            "found", artifacts={"digest": "3 rows"}, note="rows found"))

        resp = rig.gate.execute(1)

        self.assertEqual(resp.reaped, [rig.key(step)])
        self.assertEqual(
            [(c.step, c.outcome, c.note) for c in rig.complete.calls],
            [(step, "found", "rows found")])
        self.assertIn(
            ("digest", "3 rows"), [(a.type, a.value) for a in rig.store.item_artifacts(step)])

    def test_reaping_precedes_starting_so_a_slot_frees_in_the_same_tick(self):
        rig = Rig(cap=1)
        first = rig.step()
        second = rig.step()
        rig.gate.execute(0)
        rig.runner.finish(rig.key(first), done("found"))

        resp = rig.gate.execute(1)

        self.assertEqual(resp.reaped, [rig.key(first)])
        self.assertEqual(resp.started, [rig.key(second)])

    def test_no_more_than_script_max_running_run_at_once(self):
        rig = Rig(cap=2)
        for _ in range(3):
            rig.step()

        resp = rig.gate.execute(0)

        self.assertEqual(len(resp.started), 2)
        self.assertEqual(len(rig.runner.running()), 2)

    def test_a_result_for_a_step_completed_meanwhile_is_discarded(self):
        rig = Rig()
        step = rig.step()
        rig.gate.execute(0)
        rig.store.update_state(step, State.DONE)
        rig.runner.finish(rig.key(step), done("found"))

        resp = rig.gate.execute(1)

        self.assertEqual(resp.reaped, [rig.key(step)])
        self.assertEqual(rig.complete.calls, [])

    def test_a_step_with_no_script_is_left_alone(self):
        rig = Rig(stages={"poll": StepDef(routes={"found": "next"})})
        rig.step()

        self.assertEqual(rig.gate.execute(0).started, [])

    def test_guard_keys_on_the_shared_runner_are_not_reaped_here(self):
        rig = Rig()
        rig.runner.start("guard:weekly", "s", "/c", {}, "{}", 1, "guard-weekly")
        rig.runner.finish("guard:weekly", done())

        resp = rig.gate.execute(0)

        self.assertEqual(resp.reaped, [])
        self.assertEqual(rig.runner.running(), ["guard:weekly"])


class TestEnvironment(unittest.TestCase):
    def test_the_script_gets_ids_stdin_artifacts_and_the_data_dir(self):
        rig = Rig()
        step = rig.step()
        rig.store.add_artifact(step, "secret", "x", internal=True)

        rig.gate.execute(0)

        call = rig.runner.started[0]
        self.assertEqual(call["env"]["LC_WORKFLOW_SCRIPT"], "stage")
        self.assertEqual(call["env"]["LC_STEP"], step)
        self.assertEqual(call["env"]["LC_STAGE"], "poll")
        self.assertTrue(call["env"]["LC_ITEM"])
        self.assertNotIn("LC_WORKFLOW_HOOK", call["env"])
        self.assertEqual(call["cwd"], "/data/acme/build")
        self.assertEqual(call["script"], "/bundles/acme/sha1/scripts/poll.sh")
        stdin = json.loads(call["stdin"])
        self.assertEqual(stdin["stage"], "poll")
        self.assertIn({"type": "brief", "value": "hello"}, stdin["item_artifacts"])
        self.assertNotIn("secret", [a["type"] for a in stdin["step_artifacts"]])

    def test_a_scheduled_items_guard_state_reaches_the_stage_as_schedule_state(self):
        rig = Rig()
        step = rig.step()
        item = rig.store.get_node(step).item
        rig.store.add_artifact(item, "schedule-state", "batch: APP-1", internal=True)

        rig.gate.execute(0)

        stdin = json.loads(rig.runner.started[0]["stdin"])
        self.assertEqual(stdin["schedule_state"], "batch: APP-1")
        self.assertNotIn("schedule-state", [a["type"] for a in stdin["item_artifacts"]])

    def test_a_hand_filed_item_gives_the_stage_a_null_schedule_state(self):
        rig = Rig()
        rig.step()

        rig.gate.execute(0)

        stdin = json.loads(rig.runner.started[0]["stdin"])
        self.assertIn("schedule_state", stdin)
        self.assertIsNone(stdin["schedule_state"])

    def test_a_declared_workspace_runs_in_the_item_worktree(self):
        rig = Rig(
            stages={"poll": StepDef(
                script="scripts/poll.sh", routes={"found": "n"}, workspace="project")},
            worktree="/wt/item")
        step = rig.step()

        rig.gate.execute(0)

        self.assertEqual([s.id for s in rig.ensured], [step])
        self.assertEqual(rig.runner.started[0]["cwd"], "/wt/item")

    def _workspace_stage(self):
        return {"poll": StepDef(
            script="scripts/poll.sh", routes={"found": "n"}, workspace="project")}

    def test_a_workspace_with_no_worktree_parks_and_starts_nothing(self):
        rig = Rig(stages=self._workspace_stage(), worktree=None)
        step = rig.step()

        resp = rig.gate.execute(0)

        self.assertEqual(rig.runner.started, [])
        self.assertEqual(resp.parked, ["step:%s" % step])
        self.assertIn("item has no worktree", rig.store.get_node(step).park.reason)

    def test_a_failed_ensure_parks_with_its_text_and_starts_nothing(self):
        rig = Rig(stages=self._workspace_stage(), ensure_error=UseCaseError("git worktree add failed"))
        step = rig.step()

        resp = rig.gate.execute(0)

        self.assertEqual(rig.runner.started, [])
        self.assertEqual(resp.parked, ["step:%s" % step])
        self.assertIn("git worktree add failed", rig.store.get_node(step).park.reason)

    def test_a_stage_without_a_workspace_never_ensures_a_worktree(self):
        rig = Rig()
        rig.step()

        rig.gate.execute(0)

        self.assertEqual(rig.ensured, [])


class TestViolationsPark(unittest.TestCase):
    def _parked(self, result, **rig_kwargs):
        rig = Rig(**rig_kwargs)
        step = rig.step()
        rig.gate.execute(0)
        rig.runner.finish(rig.key(step), result)
        resp = rig.gate.execute(1)
        node = rig.store.get_node(step)
        return rig, step, node, resp

    def _assert_parked(self, node, *needles):
        self.assertEqual(node.role, "human")
        self.assertFalse(is_engine_step(node))
        text = node.park.reason
        for needle in needles:
            self.assertIn(needle, text)

    def test_non_zero_exit_parks_with_the_stderr_tail(self):
        _, step, node, resp = self._parked(
            ScriptResult(exit_code=2, stdout="", stderr_tail="boom: bad token"))

        self.assertEqual(resp.parked, ["step:%s" % step])
        self._assert_parked(node, "poll", "scripts/poll.sh", "exited 2", "boom: bad token")

    def test_timeout_parks(self):
        _, _, node, _ = self._parked(
            ScriptResult(exit_code=None, timed_out=True, stderr_tail="slow"))

        self._assert_parked(node, "timed out after 300s", "slow")

    def test_unparseable_stdout_parks_and_shows_it(self):
        _, _, node, _ = self._parked(ScriptResult(exit_code=0, stdout="not json"))

        self._assert_parked(node, "not one JSON object", "not json")

    def test_an_undeclared_outcome_parks(self):
        _, _, node, _ = self._parked(done("elsewhere"))

        self._assert_parked(node, "elsewhere", "not declared")

    def test_a_missing_outcome_parks(self):
        _, _, node, _ = self._parked(ScriptResult(exit_code=0, stdout="{}"))

        self._assert_parked(node, "no outcome")

    def test_an_unknown_key_parks(self):
        _, _, node, _ = self._parked(done("found", notes="typo"))

        self._assert_parked(node, "unknown key", "notes")

    def test_a_use_case_error_on_completion_parks(self):
        _, _, node, _ = self._parked(done("found"), complete_fail=UseCaseError("missing artifact x"))

        self._assert_parked(node, "completing it failed", "missing artifact x")

    def test_a_missing_required_config_key_parks_without_running_the_script(self):
        rig = Rig(lifecycle=StubScriptLifecycle(missing=("api-token",)))
        step = rig.step()

        resp = rig.gate.execute(0)

        self.assertEqual(rig.runner.started, [])
        self.assertEqual(resp.parked, ["step:%s" % step])
        self._assert_parked(rig.store.get_node(step), "api-token", "workflow-acme-build")

    def test_a_parked_step_is_no_longer_an_engine_step_and_is_not_restarted(self):
        rig, step, node, _ = self._parked(ScriptResult(exit_code=1))

        self.assertFalse(is_engine_step(node))
        self.assertEqual(rig.gate.execute(2).started, [])


class TestMixedOutcomes(unittest.TestCase):
    def test_one_completes_and_two_park_each_naming_its_own_stage(self):
        stages = {
            "good": StepDef(script="scripts/a.sh", routes={"found": "n"}),
            "crash": StepDef(script="scripts/b.sh", routes={"found": "n"}),
            "slow": StepDef(script="scripts/c.sh", routes={"found": "n"}),
        }
        rig = Rig(stages=stages)
        steps = {name: rig.step(name) for name in stages}
        rig.gate.execute(0)
        rig.runner.finish(rig.key(steps["good"]), done("found"))
        rig.runner.finish(rig.key(steps["crash"]), ScriptResult(exit_code=1, stderr_tail="x"))
        rig.runner.finish(
            rig.key(steps["slow"]), ScriptResult(exit_code=None, timed_out=True))

        resp = rig.gate.execute(1)

        self.assertEqual([c.step for c in rig.complete.calls], [steps["good"]])
        self.assertEqual(
            sorted(resp.parked), sorted(rig.key(steps[n]) for n in ("crash", "slow")))
        for name in ("crash", "slow"):
            node = rig.store.get_node(steps[name])
            self.assertEqual(node.role, "human")
            self.assertIn("stage %s" % name, node.park.reason)
