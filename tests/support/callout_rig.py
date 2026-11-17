import json
import os
from lightcycle.application.pool.callout_dispatch import CalloutDispatchUseCase, callout_key
from lightcycle.config_callouts import Callout
from lightcycle.domain.flow.flow import Flow
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.domain.work import State
from lightcycle.ports.script_runner import ScriptResult
from tests.support.fake_github import FakeGitHub
from tests.support.fake_script_runner import FakeScriptRunner
from tests.support.fake_store import FakeStore

PIN = "acme/build@sha1"


class StubConfig:
    def __init__(self, callouts):
        self._callouts = callouts

    def callouts(self):
        return list(self._callouts)

    def base_env(self):
        return {"PATH": "/bin"}

    def expand_path(self, v):
        return os.path.expanduser(v)


class StubFlowService:
    def __init__(self, defs):
        self._defs = defs

    def flow_for(self, node):
        return Flow(self._defs)

    def workflow_for(self, node):
        return PIN

    def unpinned_workflow(self, node):
        return None


class StubWorktrees:
    def item_branch(self, node):
        return None

    def worktree_path(self, node):
        return None


def callout(callout_id="a", subject="pr", wait=False, timeout=30, principal_outputs=("code",)):
    return Callout(
        id=callout_id, command="/bin/%s" % callout_id, subject=subject,
        principal_outputs=tuple(principal_outputs), wait=wait, timeout=timeout)


def ok(*artifacts):
    return ScriptResult(exit_code=0, stdout=json.dumps({
        "status": "ok", "message": "",
        "artifacts": [{"label": l, "kind": k, "value": v} for l, k, v in artifacts]}))


def preflight_ok():
    return ScriptResult(exit_code=0, stdout=json.dumps({"status": "ok"}))


def preflight_failed(*errors):
    return ScriptResult(exit_code=0, stdout=json.dumps({
        "status": "failed", "errors": [{"message": m, "fix": f} for m, f in errors]}))


class CalloutRig:
    def __init__(self, callouts, presents="pr", runner=None, github=None, defs=None):
        self.store = FakeStore()
        self.runner = runner or FakeScriptRunner()
        self.github = github or FakeGitHub()
        defs = defs or {
            "write": StepDef(phase="code", principal_output="code"),
            "gate": StepDef(presents=presents, phase="code"),
        }
        self.flow = StubFlowService(defs)
        self.config = StubConfig(callouts)
        self.use_case = CalloutDispatchUseCase(
            self.store, self.flow, self.config, self.runner, self.github, StubWorktrees())

    def gate(self, role="human", state=State.WAITING, stage="gate"):
        item = self.store.create_item("Title", "the description", workflow=PIN, shortcode="APP")
        step = self.store.create_step(stage=stage, role=role, item=item)
        self.store.update_state(step, state)
        return step

    def key(self, step, callout_id="a"):
        return callout_key(step, callout_id)

    def preflight_key(self, step, callout_id="a"):
        return callout_key(step, callout_id, "preflight")

    def pass_preflight(self, step, now, *callout_ids):
        for callout_id in callout_ids or ("a",):
            self.runner.finish(self.preflight_key(step, callout_id), preflight_ok())
        self.use_case.execute(now)

    def records(self, step):
        from lightcycle.application.work.callout_hold import callout_runs_of
        return callout_runs_of(self.store, step)

    def stdin(self, index=0):
        return json.loads(self.runner.started[index]["stdin"])

