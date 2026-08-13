from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LinkArtifactInput:
    item: str
    atype: str
    value: str
    label: Optional[str] = None
    replace: bool = False
    kind: Optional[str] = None
    internal: bool = False


class LinkArtifactUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: LinkArtifactInput) -> None:
        if input.replace:
            self._store.replace_artifact(
                input.item, input.atype, input.value, input.label,
                internal=input.internal, kind=input.kind,
            )
        else:
            self._store.add_artifact(
                input.item, input.atype, input.value, input.label,
                internal=input.internal, kind=input.kind,
            )
