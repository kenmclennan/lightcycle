from dataclasses import dataclass, field
from typing import List

from lightcycle.application.workflows.add import prune_origin
from lightcycle.application.workflows.errors import WorkflowSourceError
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT, contract_compatible
from lightcycle.domain.workflows.source import parse_source_manifest


@dataclass(frozen=True)
class UpgradeResponse:
    origin: str
    sha: str
    changed: bool
    pruned: List[str] = field(default_factory=list)


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
        previous = registry["current"]
        checkout, sha = self._source.fetch(registry["url"], registry["ref"])
        try:
            manifest = parse_source_manifest(self._source.read_manifest(checkout))
            if not contract_compatible(manifest.contract):
                raise WorkflowSourceError(
                    "source targets contract %d, engine provides %d; `lc upgrade` the engine "
                    "or use a source ref that targets %d"
                    % (manifest.contract, ENGINE_CONTRACT, ENGINE_CONTRACT))
            self._source.materialize(origin, sha, checkout)
            self._source.write_registry(origin, registry["url"], registry["ref"], sha)
            pruned = prune_origin(self._source, self._store, origin, self._config.workflow_retention())
        finally:
            self._source.cleanup(checkout)
        return UpgradeResponse(origin=origin, sha=sha, changed=(sha != previous), pruned=pruned)
