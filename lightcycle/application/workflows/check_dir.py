import os
from dataclasses import dataclass, field
from typing import List

from lightcycle.application.workflows.bundle_check import (
    check_bundle_references,
    check_prompts,
)
from lightcycle.application.workflows.prompt_check import (
    PromptSurfaceUnavailable,
    engine_sources,
    prompt_drift_detail,
)
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


class CheckWorkflowDirUseCase:
    def __init__(self, bundle_port, fs):
        self._bundle = bundle_port
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
        return FetchedBundle(
            manifest=manifest, sha=DIR_SHA, steps=steps, workflows=workflows)

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
        references = {
            n: msgs for n, msgs in check_bundle_references(bundle).items() if n in names
        }
        try:
            detail = prompt_drift_detail(check_prompts(bundle, *engine_sources(self._fs)))
        except PromptSurfaceUnavailable as e:
            detail = "could not determine the engine's prompt-check surface: %s" % e
        if detail:
            problems.append(detail)
        return DirCheckResponse(names=names, problems=problems, reference_problems=references)
