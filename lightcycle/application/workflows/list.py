from dataclasses import dataclass, field
from typing import List

from lightcycle.application.workflows.pinned import pinned_shas


@dataclass(frozen=True)
class OriginView:
    name: str
    url: str
    ref: str
    current: str
    versions: List[str] = field(default_factory=list)
    pinned: List[str] = field(default_factory=list)
    workflows: List = field(default_factory=list)


@dataclass(frozen=True)
class ListResponse:
    origins: List[OriginView] = field(default_factory=list)


class ListWorkflowSourcesUseCase:
    def __init__(self, source, store, fs=None):
        self._source = source
        self._store = store
        self._fs = fs

    def _workflows(self, origin, current):
        if not current or self._fs is None:
            return []
        root = self._source.pinned_bundle(origin, current)
        return [
            (wf, self._fs.workflow_meta(wf, root).get("summary", ""))
            for wf in sorted(self._source.workflow_names(origin, current))
        ]

    def execute(self) -> ListResponse:
        origins = []
        for name in self._source.list_origins():
            registry = self._source.read_registry(name)
            current = registry.current if registry else None
            origins.append(OriginView(
                name=name,
                url=registry.url if registry else None,
                ref=registry.ref if registry else None,
                current=current,
                versions=self._source.list_versions(name),
                pinned=sorted(pinned_shas(self._store, name)),
                workflows=self._workflows(name, current),
            ))
        return ListResponse(origins=origins)
