from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.workflows.add import prune_origin_best_effort
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
from lightcycle.application.workflows.lifecycle import bundle_lifecycles, validate_fetched_bundle
from lightcycle.application.workflows.engine_requirement_check import unmet_requirement_message
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT, contract_compatible
from lightcycle.domain.workflows.source import parse_source_manifest
from lightcycle.ports.workflow_source import WorkflowSourceError


@dataclass(frozen=True)
class UpgradeResponse:
    origin: str
    sha: str
    changed: bool
    pruned: List[str] = field(default_factory=list)
    prune_error: Optional[str] = None


@dataclass(frozen=True)
class UpgradeOriginFailure:
    origin: str
    error: str


@dataclass(frozen=True)
class UpgradeAllResponse:
    results: List[UpgradeResponse] = field(default_factory=list)
    failures: List[UpgradeOriginFailure] = field(default_factory=list)


class UpgradeWorkflowSourceUseCase:
    def __init__(self, source, store, config, fs, lifecycle):
        self._source = source
        self._store = store
        self._config = config
        self._fs = fs
        self._lifecycle = lifecycle

    def _previous_declarations(self, origin, previous):
        if not self._source.has_version(origin, previous):
            return {}
        declared = {}
        for name in self._source.workflow_names(origin, previous):
            try:
                found = self._lifecycle.declared(origin, name, previous)
            except ValueError:
                found = None
            declared[name] = found
        return declared

    def _run_hooks(self, origin, bundle, previous):
        before = self._previous_declarations(origin, previous)
        created = []
        try:
            for name, declared in sorted(bundle_lifecycles(bundle).items()):
                prior = before.get(name)
                if declared.install and not (prior and prior.install):
                    if not self._lifecycle.data_dir_exists(origin, name):
                        created.append(name)
                    self._must(self._lifecycle.install(origin, name, bundle.sha))
                if declared.upgrade and name in before:
                    if not self._lifecycle.data_dir_exists(origin, name):
                        created.append(name)
                    self._must(self._lifecycle.upgrade(origin, name, previous, bundle.sha))
        except WorkflowSourceError:
            for made in created:
                self._lifecycle.remove_data_dir(origin, made)
            raise

    @staticmethod
    def _must(outcome):
        if not outcome.ok:
            raise WorkflowSourceError(outcome.detail)

    def execute(self, origin) -> UpgradeResponse:
        keep_n = self._config.workflow_retention()
        registry = self._source.read_registry(origin)
        if registry is None:
            raise WorkflowSourceError(
                "origin %r is not registered; use `lc workflow add <url> --name %s`"
                % (origin, origin))
        previous = registry.current
        bundle = self._source.fetch(registry.url, registry.ref)
        manifest = parse_source_manifest(bundle.manifest)
        if not contract_compatible(manifest.contract):
            raise WorkflowSourceError(
                "source targets contract %d, engine provides %d; `lc upgrade` the engine "
                "or use a source ref that targets %d"
                % (manifest.contract, ENGINE_CONTRACT, ENGINE_CONTRACT))
        if (manifest.requires_engine is not None
                and not manifest.requires_engine.satisfied_by(self._config.version())):
            raise WorkflowSourceError(
                unmet_requirement_message(manifest.requires_engine, self._config.version()))
        problems = check_bundle_references(bundle)
        if problems:
            detail = "; ".join(
                "%r: %s" % (wf, "; ".join(messages))
                for wf, messages in sorted(problems.items())
            )
            raise WorkflowSourceError(
                "bundle has composition problem(s) - %s" % detail)
        try:
            sources = engine_sources(self._fs)
            fragments = engine_fragment_names(self._fs)
        except PromptSurfaceUnavailable as e:
            raise WorkflowSourceError(
                "could not determine the engine's prompt-check surface: %s" % e)
        detail = prompt_drift_detail(
            merge_problems(
                check_prompts(bundle, *sources),
                check_step_structure_for(bundle, fragments),
            )
        )
        if detail:
            raise WorkflowSourceError("bundle prompts do not match this engine - %s" % detail)
        validate_fetched_bundle(bundle)
        existed = self._source.has_version(origin, bundle.sha)
        self._source.pin(origin, bundle)
        if bundle.sha != previous:
            try:
                self._run_hooks(origin, bundle, previous)
            except WorkflowSourceError:
                if not existed:
                    self._source.remove_version(origin, bundle.sha)
                raise
        self._source.write_registry(origin, registry.url, registry.ref, bundle.sha, registry.writable)
        pruned, prune_error = prune_origin_best_effort(self._source, self._store, origin, keep_n)
        return UpgradeResponse(
            origin=origin, sha=bundle.sha, changed=(bundle.sha != previous),
            pruned=pruned, prune_error=prune_error)


class UpgradeWorkflowSourcesUseCase:
    def __init__(self, source, store, config, fs, lifecycle):
        self._source = source
        self._single = UpgradeWorkflowSourceUseCase(source, store, config, fs, lifecycle)

    def execute(self, origin=None) -> UpgradeAllResponse:
        origins = [origin] if origin else self._source.list_origins()
        results = []
        failures = []
        for o in origins:
            try:
                results.append(self._single.execute(o))
            except WorkflowSourceError as e:
                failures.append(UpgradeOriginFailure(origin=o, error=str(e)))
        return UpgradeAllResponse(results=results, failures=failures)
