import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.schedule.guards import is_script_guard, script_guard_path
from lightcycle.domain.workflows.script_stage import (
    GUARD_OUTCOMES,
    fixture_path,
    parse_fixture,
    script_path_problem,
)

SCRIPT_STDERR_TAIL = 2000


@dataclass(frozen=True)
class ScriptInvocation:
    script: str
    cwd: str
    env: Dict[str, str]
    stdin_text: str


@dataclass(frozen=True)
class ScriptStageDecl:
    stage: str
    path: str
    outcomes: Tuple[str, ...]
    workspace: Optional[str] = None
    problems: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ScriptDecls:
    stages: List[ScriptStageDecl] = field(default_factory=list)
    guards: List[str] = field(default_factory=list)


def _on_pr_hooks(step_def):
    return sorted(h for h in step_def.hooks if h.startswith("on_pr_"))


def stage_structure_problems(stage, meta, step_def, outcomes):
    problems = []
    if meta.get("model"):
        problems.append("script stage %s has both script: and model: (two owners)" % stage)
    if not outcomes:
        problems.append("script stage %s declares no outcome" % stage)
    if step_def.ci_success is not None or step_def.ci_failure is not None:
        problems.append(
            "script stage %s declares ci_success/ci_failure, which would be a second way "
            "to complete it" % stage)
    hooks = _on_pr_hooks(step_def)
    if hooks:
        problems.append(
            "script stage %s declares %s, which would be a second way to complete it"
            % (stage, ", ".join(hooks)))
    return problems


class WorkflowScripts:
    def __init__(self, bundle, fs):
        self._bundle = bundle
        self._fs = fs

    def _step_metas(self, directory):
        metas = {}
        for role in self._bundle.step_roles(directory):
            parsed = self._bundle.parse_step(role, directory)
            metas[role] = parsed.meta if parsed else {}
        return metas

    def _guards(self, directory, name):
        block = self._bundle.workflow_meta(name, directory).get("schedule")
        if isinstance(block, dict) and is_script_guard(str(block.get("guard", ""))):
            return [script_guard_path(str(block["guard"]))]
        return []

    def _stages(self, directory, name):
        text = self._bundle.workflow_text(name, directory)
        if text is None:
            return []
        try:
            graph = parse_graph(text)
            metas = self._step_metas(directory)
        except ValueError:
            return []
        flow = Flow.from_graph(graph, metas)
        stages = []
        for stage in flow.steps():
            step_def = flow.step_def(stage)
            if not step_def.script:
                continue
            meta = metas.get(graph.file_for(stage), {})
            outcomes = tuple(sorted((graph.edges.get(stage) or {}).keys()))
            stages.append(ScriptStageDecl(
                stage=stage, path=step_def.script, outcomes=outcomes,
                workspace=graph.workspaces.get(stage),
                problems=tuple(stage_structure_problems(stage, meta, step_def, outcomes))))
        return stages

    def declarations(self, directory, name):
        return ScriptDecls(
            stages=self._stages(directory, name), guards=self._guards(directory, name))

    def uses_scripts(self, directory, name):
        decls = self.declarations(directory, name)
        return bool(decls.stages or decls.guards)

    def _path_problems(self, directory, label, path):
        shape = script_path_problem(label, path)
        if shape:
            return [shape]
        full = os.path.join(directory, *path.split("/"))
        if not self._fs.exists(full):
            return ["%s %s does not exist" % (label, path)]
        if not self._fs.is_executable(full):
            return ["%s %s is not executable" % (label, path)]
        return []

    def read_fixture(self, directory, path, outcomes, guard=False):
        rel = fixture_path(path)
        data = self._fs.read_bytes(os.path.join(directory, *rel.split("/")))
        if data is None:
            raise ValueError("fixture %s does not exist" % rel)
        try:
            return parse_fixture(data.decode("utf-8"), outcomes, guard=guard)
        except ValueError as e:
            raise ValueError("fixture %s: %s" % (rel, e))

    def problems(self, directory, name):
        decls = self.declarations(directory, name)
        found = []
        for decl in decls.stages:
            found.extend(decl.problems)
            label = "script stage %s script" % decl.stage
            path_problems = self._path_problems(directory, label, decl.path)
            found.extend(path_problems)
            if not path_problems and decl.outcomes:
                try:
                    self.read_fixture(directory, decl.path, decl.outcomes)
                except ValueError as e:
                    found.append("script stage %s: %s" % (decl.stage, e))
        for path in decls.guards:
            path_problems = self._path_problems(directory, "script guard", path)
            found.extend(path_problems)
            if not path_problems:
                try:
                    self.read_fixture(directory, path, GUARD_OUTCOMES, guard=True)
                except ValueError as e:
                    found.append("script guard: %s" % e)
        return found


def describe_violation(label, reason, result=None, stdout_too=False):
    text = "%s %s" % (label, reason)
    if result is not None:
        tail = (result.stderr_tail or "").strip()
        if tail:
            text += "\nstderr tail:\n%s" % tail[-SCRIPT_STDERR_TAIL:]
        if stdout_too and (result.stdout or "").strip():
            text += "\nstdout:\n%s" % result.stdout.strip()[-SCRIPT_STDERR_TAIL:]
    return text


def result_violation(result, timeout):
    if result.timed_out:
        return "timed out after %ss" % timeout, False
    if result.exit_code is None:
        return "could not start", False
    if result.exit_code != 0:
        return "exited %d" % result.exit_code, False
    return None, True


def stdin_for_stage(item, step, stage, item_artifacts, step_artifacts):
    def visible(artifacts):
        return [{"type": a.type, "value": a.value} for a in artifacts if not a.internal]

    return json.dumps({
        "item": item, "step": step, "stage": stage,
        "item_artifacts": visible(item_artifacts),
        "step_artifacts": visible(step_artifacts),
    })


def stdin_for_guard(schedule_id, last_state):
    return json.dumps({"schedule": schedule_id, "last_state": last_state})
