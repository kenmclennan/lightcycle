from dataclasses import dataclass, field
from typing import List

from lightcycle.application.workflows.pinned import pinned_shas
from lightcycle.ports.workflow_source import WorkflowSourceError


@dataclass(frozen=True)
class RemoveResponse:
    origin: str
    kept_data_dirs: List[str] = field(default_factory=list)


class RemoveWorkflowSourceUseCase:
    def __init__(self, source, store, lifecycle):
        self._source = source
        self._store = store
        self._lifecycle = lifecycle

    def execute(self, origin) -> RemoveResponse:
        if self._source.read_registry(origin) is None:
            raise WorkflowSourceError("origin %r is not registered" % origin)
        pinned = pinned_shas(self._store, origin)
        if pinned:
            raise WorkflowSourceError(
                "refusing to remove %r: live items pin %s"
                % (origin, ", ".join(sorted(pinned))))
        self._source.remove_origin(origin)
        return RemoveResponse(
            origin=origin, kept_data_dirs=self._lifecycle.kept_data_dirs(origin))
