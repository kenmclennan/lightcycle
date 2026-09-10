from dataclasses import dataclass, field
from typing import List

from lightcycle.application.workflows.add import prune_origin
from lightcycle.application.workflows.bundle_check import (
    check_bundle_references,
    check_prompts,
)
from lightcycle.application.workflows.prompt_check import (
    engine_sources,
    prompt_drift_detail,
)
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT, contract_compatible
from lightcycle.domain.workflows.source import parse_source_manifest
from lightcycle.ports.workflow_source import WorkflowSourceError


@dataclass(frozen=True)
class UpgradeResponse:
    origin: str
    sha: str
    changed: bool
    pruned: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class UpgradeOriginFailure:
    origin: str
    error: str


@dataclass(frozen=True)
class UpgradeAllResponse:
    results: List[UpgradeResponse] = field(default_factory=list)
    failures: List[UpgradeOriginFailure] = field(default_factory=list)


class UpgradeWorkflowSourceUseCase:
    def __init__(self, source, store, config):
        self._source = source
        self._store = store
        self._config = config

    def execute(self, origin) -> UpgradeResponse:
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
        problems = check_bundle_references(bundle)
        if problems:
            detail = "; ".join(
                "%r: %s" % (wf, "; ".join(messages))
                for wf, messages in sorted(problems.items())
            )
            raise WorkflowSourceError(
                "bundle has composition problem(s) - %s" % detail)
        detail = prompt_drift_detail(
            check_prompts(bundle, *engine_sources())
        )
        if detail:
            raise WorkflowSourceError("bundle prompts do not match this engine - %s" % detail)
        self._source.pin(origin, bundle)
        self._source.write_registry(origin, registry.url, registry.ref, bundle.sha)
        pruned = prune_origin(self._source, self._store, origin, self._config.workflow_retention())
        return UpgradeResponse(
            origin=origin, sha=bundle.sha, changed=(bundle.sha != previous), pruned=pruned)


class UpgradeWorkflowSourcesUseCase:
    def __init__(self, source, store, config):
        self._source = source
        self._single = UpgradeWorkflowSourceUseCase(source, store, config)

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
