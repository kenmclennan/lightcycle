from dataclasses import dataclass
from typing import List

from the_grid.application.errors import UseCaseError
from the_grid.domain.work import MigratedTask, seed_counters


@dataclass(frozen=True)
class MigrateFromBdExportInput:
    tasks: List[MigratedTask]
    force: bool = False


@dataclass(frozen=True)
class MigrateFromBdExportResponse:
    migrated_count: int


class MigrateFromBdExportUseCase:
    def __init__(self, target_store):
        self._target = target_store

    def execute(self, input: MigrateFromBdExportInput) -> MigrateFromBdExportResponse:
        if not input.force and not self._target.is_empty():
            raise UseCaseError(
                "target store is not empty; pass force=True to migrate into it anyway"
            )
        for task in input.tasks:
            self._target.import_task(task)
        seeds = seed_counters(input.tasks, self._target.shortcode())
        for namespace, next_value in seeds.items():
            self._target.seed_counter(namespace, next_value)
        return MigrateFromBdExportResponse(migrated_count=len(input.tasks))
