from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ListWorkersResponse:
    workers: List[dict]


class ListWorkersUseCase:
    def __init__(self, workers, store=None):
        self._workers = workers
        self._store = store

    def execute(self) -> ListWorkersResponse:
        return ListWorkersResponse(
            workers=[
                dict(
                    w,
                    alive=self._workers.pid_alive(w.get("pid", -1), w.get("pid_started")),
                    stage=self._stage_of(w.get("step")),
                )
                for w in self._workers.workers_state()
            ]
        )

    def _stage_of(self, step_id):
        if not (step_id and self._store):
            return None
        try:
            return self._store.get_node(step_id).step
        except KeyError:
            return None
