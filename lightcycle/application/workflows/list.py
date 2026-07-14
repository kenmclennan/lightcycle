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


@dataclass(frozen=True)
class ListResponse:
    origins: List[OriginView] = field(default_factory=list)


class ListWorkflowSourcesUseCase:
    def __init__(self, source, store):
        self._source = source
        self._store = store

    def execute(self) -> ListResponse:
        origins = []
        for name in self._source.list_origins():
            registry = self._source.read_registry(name) or {}
            origins.append(OriginView(
                name=name,
                url=registry.get("url"),
                ref=registry.get("ref"),
                current=registry.get("current"),
                versions=self._source.list_versions(name),
                pinned=sorted(pinned_shas(self._store, name)),
            ))
        return ListResponse(origins=origins)
