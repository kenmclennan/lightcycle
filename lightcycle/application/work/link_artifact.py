from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LinkArtifactInput:
    item: str
    atype: str
    value: str
    label: Optional[str] = None


class LinkArtifactUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: LinkArtifactInput) -> None:
        self._store.add_artifact(input.item, input.atype, input.value, input.label)
