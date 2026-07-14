from dataclasses import dataclass, field
from typing import List

from lightcycle.application.workflows.errors import WorkflowSourceError
from lightcycle.application.workflows.pinned import pinned_shas
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT, contract_compatible
from lightcycle.domain.workflows.retention import versions_to_prune
from lightcycle.domain.workflows.source import parse_source_manifest


@dataclass(frozen=True)
class AddResponse:
    origin: str
    sha: str
    pruned: List[str] = field(default_factory=list)


def prune_origin(source, store, origin, keep_n):
    pruned = versions_to_prune(
        source.list_versions(origin), keep_n, pinned_shas(store, origin)
    )
    for sha in pruned:
        source.remove_version(origin, sha)
    return pruned


class AddWorkflowSourceUseCase:
    def __init__(self, source, store, config):
        self._source = source
        self._store = store
        self._config = config

    def execute(self, url, ref, name) -> AddResponse:
        checkout, sha = self._source.fetch(url, ref)
        try:
            manifest = parse_source_manifest(self._source.read_manifest(checkout))
            origin = name or manifest.name
            if not origin:
                raise WorkflowSourceError(
                    "source declares no name; pass --name to name the origin")
            if not contract_compatible(manifest.contract):
                raise WorkflowSourceError(
                    "source targets contract %d, engine provides %d; `lc upgrade` the engine "
                    "or use a source ref that targets %d"
                    % (manifest.contract, ENGINE_CONTRACT, ENGINE_CONTRACT))
            if self._source.read_registry(origin) is not None:
                raise WorkflowSourceError(
                    "origin %r is already registered; use `lc workflow upgrade %s`"
                    % (origin, origin))
            self._source.materialize(origin, sha, checkout)
            self._source.write_registry(origin, url, ref, sha)
            pruned = prune_origin(self._source, self._store, origin, self._config.workflow_retention())
        finally:
            self._source.cleanup(checkout)
        return AddResponse(origin=origin, sha=sha, pruned=pruned)
