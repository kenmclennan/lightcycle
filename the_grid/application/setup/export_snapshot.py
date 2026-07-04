import json
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ExportSnapshotResponse:
    lines: List[str]


class ExportSnapshotUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self) -> ExportSnapshotResponse:
        rows = self._store.export_rows()
        return ExportSnapshotResponse(lines=[json.dumps(row) for row in rows])
