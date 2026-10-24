import os
from dataclasses import dataclass, field
from typing import List

from lightcycle.frontmatter import split_frontmatter
from lightcycle.application.workflows.bundle_check import (
    check_bundle_references,
    check_prompts,
    check_step_structure_for,
    merge_problems,
)
from lightcycle.application.workflows.prompt_check import (
    PromptSurfaceUnavailable,
    engine_fragment_names,
    engine_sources,
    prompt_drift_detail,
)
from lightcycle.application.workflows.engine_requirement_check import unmet_requirement_message
from lightcycle.application.workflows.script_tooling import WorkflowScripts
from lightcycle.application.workflows.lifecycle import (
    directory_lifecycle,
    directory_lifecycle_problems,
)
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT, contract_compatible
from lightcycle.domain.workflows.source import parse_source_manifest
from lightcycle.ports.workflow_source import FetchedBundle, WorkflowSourceError

DIR_ORIGIN = "dir"
DIR_SHA = "local"


class DirWorkflowSource:
    def __init__(self, directory):
        self._directory = directory

    def pinned_bundle(self, origin, sha):
        return self._directory


@dataclass(frozen=True)
class DirCheckResponse:
    names: List[str]
    problems: List[str] = field(default_factory=list)
    reference_problems: dict = field(default_factory=dict)
    lifecycle_problems: dict = field(default_factory=dict)


class CheckWorkflowDirUseCase:
    def __init__(self, bundle_port, fs, engine_version, config):
        self._bundle = bundle_port
        self._engine_version = engine_version
        self._config = config
        self._fs = fs

    def _read(self, path):
        data = self._fs.read_bytes(path)
        return None if data is None else data.decode("utf-8")

    def _read_bundle(self, directory):
        manifest = self._read(os.path.join(directory, "source.toml"))
        if manifest is None:
            raise WorkflowSourceError("%s has no source.toml" % directory)
        available = self._bundle.workflow_names(directory)
        if not available:
            raise WorkflowSourceError("%s has no workflows/*.md" % directory)
        steps = {
            role: self._read(os.path.join(directory, "steps", "%s.md" % role))
            for role in self._bundle.step_roles(directory)
        }
        workflows = {
            n: self._bundle.workflow_text(n, directory) for n in available
        }
        fragments_dir = os.path.join(directory, "fragments")
        fragments = {
            rel[: -len(".md")]: self._read(os.path.join(fragments_dir, rel))
            for rel in self._fs.list_files(fragments_dir)
            if rel.endswith(".md") and "/" not in rel
        }
        return FetchedBundle(
            manifest=manifest, sha=DIR_SHA, steps=steps, workflows=workflows,
            fragments=fragments)

    @staticmethod
    def _bound_outcomes(bundle, role):
        outcomes = set()
        for text in bundle.workflows.values():
            try:
                graph = parse_graph(text or "")
            except ValueError:
                continue
            for stage, routes in graph.edges.items():
                if graph.file_for(stage) == role:
                    outcomes.update(routes)
        return outcomes

    def _outcome_marker_problems(self, bundle, manifest):
        problems = []
        for role in sorted(bundle.steps):
            step_meta, _ = split_frontmatter(bundle.steps[role] or "")
            for key in ("review", "sends-back"):
                if key not in step_meta:
                    continue
                declared = [
                    o.strip() for o in str(step_meta[key] or "").split(",") if o.strip()]
                if not declared:
                    problems.append("step %s declares an empty %s:" % (role, key))
                if key == "review" and len(declared) > 1:
                    problems.append(
                        "step %s declares review: %r; it takes one pass outcome"
                        % (role, step_meta[key]))
                known = self._bound_outcomes(bundle, role)
                for outcome in declared:
                    if outcome not in known:
                        problems.append(
                            "step %s declares %s: %s, which is not an outcome in an edges: "
                            "line of any stage bound to it" % (role, key, outcome))
                if manifest.requires_engine is None:
                    problems.append(
                        "step %s declares %s: but source.toml has no requires-engine; "
                        "older engines would ignore it" % (role, key))
        return problems

    def execute(self, directory, name) -> DirCheckResponse:
        if name is not None and ("/" in name or "@" in name):
            raise WorkflowSourceError(
                "with --dir the workflow is a bare name like 'spec-driven', not %r" % name)
        bundle = self._read_bundle(directory)
        if name is not None and name not in bundle.workflows:
            raise WorkflowSourceError(
                "workflow %r not found in %s/workflows" % (name, directory))
        names = [name] if name is not None else sorted(bundle.workflows)
        try:
            manifest = parse_source_manifest(bundle.manifest)
        except ValueError as e:
            raise WorkflowSourceError(str(e))
        problems = []
        if not contract_compatible(manifest.contract):
            problems.append(
                "source targets contract %d, engine provides %d"
                % (manifest.contract, ENGINE_CONTRACT))
        if (manifest.requires_engine is not None
                and not manifest.requires_engine.satisfied_by(self._engine_version)):
            problems.append(
                unmet_requirement_message(manifest.requires_engine, self._engine_version))
        if manifest.requires_engine is None:
            for wf_name in sorted(bundle.workflows):
                meta, _ = split_frontmatter(bundle.workflows[wf_name] or "")
                if isinstance(meta.get("schedule"), dict) and meta["schedule"]:
                    problems.append(
                        "workflow %s declares schedule: but source.toml has no requires-engine; "
                        "older engines would ignore it" % wf_name)
        for role in sorted(bundle.steps):
            step_meta, _ = split_frontmatter(bundle.steps[role] or "")
            if "github" in step_meta:
                if str(step_meta["github"]).strip() != "heavy":
                    problems.append(
                        "step %s declares github: %r; the only accepted value is heavy"
                        % (role, step_meta["github"]))
                if manifest.requires_engine is None:
                    problems.append(
                        "step %s declares github: but source.toml has no requires-engine; "
                        "older engines would ignore it" % role)
            if "always-run" in step_meta:
                if str(step_meta["always-run"]).strip().lower() != "true":
                    problems.append(
                        "step %s declares always-run: %r; the only accepted value is true"
                        % (role, step_meta["always-run"]))
                if manifest.requires_engine is None:
                    problems.append(
                        "step %s declares always-run: but source.toml has no requires-engine; "
                        "older engines would ignore it" % role)
        problems.extend(self._outcome_marker_problems(bundle, manifest))
        lifecycle_found = {}
        scripts = WorkflowScripts(self._bundle, self._fs, self._config)
        for wf_name in names:
            found = directory_lifecycle_problems(self._bundle, self._fs, directory, wf_name)
            found = found + scripts.problems(directory, wf_name)
            if manifest.requires_engine is None and scripts.uses_scripts(directory, wf_name):
                found = found + [
                    "workflow %s declares script stages or a script guard but source.toml has "
                    "no requires-engine; older engines would ignore them" % wf_name]
            declared, _ = directory_lifecycle(self._bundle, directory, wf_name)
            if declared is not None and manifest.requires_engine is None:
                found = found + [
                    "workflow %s declares lifecycle: but source.toml has no requires-engine; "
                    "older engines would ignore it" % wf_name]
            if found:
                lifecycle_found[wf_name] = found
        references = {
            n: msgs for n, msgs in check_bundle_references(bundle).items() if n in names
        }
        try:
            detail = prompt_drift_detail(
                merge_problems(
                    check_prompts(bundle, *engine_sources()),
                    check_step_structure_for(bundle, engine_fragment_names(self._fs)),
                )
            )
        except PromptSurfaceUnavailable as e:
            detail = "could not determine the engine's prompt-check surface: %s" % e
        if detail:
            problems.append(detail)
        return DirCheckResponse(
            names=names, problems=problems, reference_problems=references,
            lifecycle_problems=lifecycle_found)
