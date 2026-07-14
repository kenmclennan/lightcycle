from dataclasses import dataclass

from lightcycle.application.workflows.errors import WorkflowSourceError
from lightcycle.application.workflows.pinned import pinned_shas


@dataclass(frozen=True)
class RemoveResponse:
    origin: str


class RemoveWorkflowSourceUseCase:
    def __init__(self, source, store):
        self._source = source
        self._store = store

    def execute(self, origin) -> RemoveResponse:
        if self._source.read_registry(origin) is None:
            raise WorkflowSourceError("origin %r is not registered" % origin)
        pinned = pinned_shas(self._store, origin)
        if pinned:
            raise WorkflowSourceError(
                "refusing to remove %r: live items pin %s"
                % (origin, ", ".join(sorted(pinned))))
        self._source.remove_origin(origin)
        return RemoveResponse(origin=origin)
