import os
from dataclasses import dataclass, field
from typing import List, Tuple

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.park_step import ParkInput
from lightcycle.application.flow.script_result import apply_stage_result
from lightcycle.application.pool.pr_lookups import flow_for, skip_unpinned
from lightcycle.application.workflows.script_tooling import (
    ScriptInvocation,
    describe_violation,
    result_violation,
    stdin_for_stage,
)
from lightcycle.application.work.release_holds import ReleaseHolds
from lightcycle.application.work.item_outputs import ItemOutputs
from lightcycle.application.work.step_inputs import StepInputs
from lightcycle.domain.work import State, is_engine_step, script_log_label
from lightcycle.domain.workflows.identity import parse_pin
from lightcycle.domain.workflows.script_stage import parse_stage_output
from lightcycle.ports.store import NodeNotFoundError

STEP_KEY_PREFIX = "step:"


@dataclass(frozen=True)
class ScriptStagesResponse:
    started: List[str] = field(default_factory=list)
    reaped: List[str] = field(default_factory=list)
    parked: List[str] = field(default_factory=list)
    refused: List[Tuple[str, str]] = field(default_factory=list)


def step_key(step_id):
    return STEP_KEY_PREFIX + step_id


class ScriptStageUseCase:
    def __init__(self, store, flow_service, config, source, lifecycle, runner, park, complete,
                 worktrees):
        self._store = store
        self._flow_service = flow_service
        self._config = config
        self._source = source
        self._lifecycle = lifecycle
        self._runner = runner
        self._park = park
        self._complete = complete
        self._worktrees = worktrees

    def reset(self):
        return None

    def in_flight(self):
        return [k for k in self._runner.running() if k.startswith(STEP_KEY_PREFIX)]

    def execute(self, now: float) -> ScriptStagesResponse:
        reaped, parked, refused = self._reap()
        started, start_parked = self._start()
        return ScriptStagesResponse(
            started=started, reaped=reaped, parked=parked + start_parked, refused=refused)

    def _label(self, step, sd):
        pin = self._flow_service.workflow_for(step) or "?"
        return "workflow %s stage %s script %s" % (pin, step.stage, sd.script)

    def _park_step(self, step, label, reason, result=None, stdout_too=False):
        self._park.execute(ParkInput(
            step=step.id,
            observation=describe_violation(label, reason, result, stdout_too),
            decision="Fix the script or its config, then resolve the step."))

    def _reap(self):
        reaped, parked, refused = [], [], []
        for key in self._runner.running():
            if not key.startswith(STEP_KEY_PREFIX):
                continue
            result = self._runner.poll(key)
            if result is None:
                continue
            reaped.append(key)
            was_parked, refusal = self._reap_one(key[len(STEP_KEY_PREFIX):], result)
            if was_parked:
                parked.append(key)
            if refusal:
                refused.append(refusal)
        return reaped, parked, refused

    def _reap_one(self, step_id, result):
        try:
            step = self._store.get_node(step_id)
        except NodeNotFoundError:
            return False, None
        if step.state != State.QUEUED or not is_engine_step(step):
            return False, None
        if skip_unpinned(self._store, self._flow_service, step):
            return False, None
        sd = flow_for(self._flow_service, step).step_def(step.stage)
        label = self._label(step, sd)
        reason, ok = result_violation(result, self._config.script_timeout_seconds())
        if not ok:
            self._park_step(step, label, reason, result)
            return True, None
        try:
            output = parse_stage_output(result.stdout, sorted(sd.routes))
        except ValueError as e:
            self._park_step(step, label, "broke the output contract: %s" % e, result, True)
            return True, None
        try:
            resp = apply_stage_result(self._store, self._complete, step.id, output)
        except UseCaseError as e:
            self._park_step(
                step, label, "printed outcome %s but completing it failed: %s"
                % (output.outcome, e), result)
            return True, None
        if resp.teardown_refusal:
            return False, (step.item, resp.teardown_refusal)
        return False, None

    def _start(self):
        started, parked = [], []
        running = set(self._runner.running()) | {
            k for k in self._runner.orphaned() if k.startswith(STEP_KEY_PREFIX)}
        cap = self._config.script_max_running()
        queued = [
            s for s in self._store.all_steps()
            if s.state == State.QUEUED and is_engine_step(s)]
        held = ReleaseHolds(self._store, self._flow_service).held_ids(queued)
        for step in queued:
            if len(running) >= cap:
                break
            if step.id in held:
                continue
            key = step_key(step.id)
            if key in running:
                continue
            if skip_unpinned(self._store, self._flow_service, step):
                continue
            sd = flow_for(self._flow_service, step).step_def(step.stage)
            if not sd.script:
                continue
            outcome = self._start_one(step, sd, key)
            if outcome == "started":
                started.append(key)
                running.add(key)
            else:
                parked.append(key)
        return started, parked

    def _invocation(self, step, sd):
        pin = self._flow_service.workflow_for(step)
        parsed = parse_pin(pin) if pin else None
        if parsed is None:
            return None, "the item has no pinned workflow"
        origin, name, sha = parsed
        bundle_dir = self._source.pinned_bundle(origin, sha)
        extra = {"LC_ITEM": step.item, "LC_STEP": step.id, "LC_STAGE": step.stage}
        env, missing = self._lifecycle.script_environment(
            origin, name, sha, bundle_dir, "stage", extra)
        if missing:
            return None, "missing required config key(s) %s in %s" % (
                ", ".join(missing), self._config.workflow_config_block_name(origin, name))
        cwd = self._lifecycle.ensure_data_dir(origin, name)
        workspace = self._flow_service.flow_for(step).declared_workspace_of(step.stage)
        if workspace is not None:
            cwd = self._worktrees.ensure(step)
            if not cwd:
                return None, "the stage declares workspace %s but the item has no worktree" % (
                    workspace)
        stdin = stdin_for_stage(
            step.item, step.id, step.stage,
            ItemOutputs(self._store, self._flow_service).reader_artifacts(step),
            self._store.item_artifacts(step.id))
        script = os.path.join(bundle_dir, *sd.script.split("/"))
        return ScriptInvocation(script, cwd, env, stdin), None

    def _start_one(self, step, sd, key):
        label = self._label(step, sd)
        try:
            invocation, problem = self._invocation(step, sd)
        except (ValueError, UseCaseError) as e:
            invocation, problem = None, str(e)
        if invocation is None:
            self._park_step(step, label, "cannot start: %s" % problem)
            return "parked"
        StepInputs(self._store, self._flow_service).freeze(step)
        log_path = self._runner.start(
            key, invocation.script, invocation.cwd, invocation.env, invocation.stdin_text,
            self._config.script_timeout_seconds(), script_log_label(step.id))
        if log_path:
            self._store.set_log(step.id, log_path)
        return "started"
