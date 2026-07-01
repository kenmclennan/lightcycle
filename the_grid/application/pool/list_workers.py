"""ListWorkers: the running workers with liveness (role, task, pid, alive/dead)."""
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ListWorkersResponse:
    workers: List[dict]


class ListWorkersUseCase:

    def __init__(self, workers):
        self._workers = workers

    def execute(self) -> ListWorkersResponse:
        return ListWorkersResponse(workers=[
            dict(w, alive=self._workers.pid_alive(w.get("pid", -1)))
            for w in self._workers.workers_state()])
