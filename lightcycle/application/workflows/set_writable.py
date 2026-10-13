from dataclasses import dataclass

from lightcycle.ports.workflow_source import WorkflowSourceError


@dataclass(frozen=True)
class SetWritableResponse:
    origin: str
    writable: bool


class SetOriginWritableUseCase:
    def __init__(self, source):
        self._source = source

    def execute(self, origin, writable) -> SetWritableResponse:
        registration = self._source.read_registry(origin)
        if registration is None:
            known = self._source.list_origins()
            raise WorkflowSourceError(
                "origin %r is not registered; registered origins: %s"
                % (origin, ", ".join(known) if known else "none registered"))
        self._source.write_registry(
            origin, registration.url, registration.ref, registration.current, writable)
        return SetWritableResponse(origin=origin, writable=writable)
