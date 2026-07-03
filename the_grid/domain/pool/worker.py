from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Worker:
    spawnid: Optional[str] = None
    pid: Optional[int] = None
    role: Optional[str] = None
    task: Optional[str] = None
    started: float = 0

    @classmethod
    def from_state(cls, d) -> "Worker":
        return cls(
            spawnid=d.get("spawnid"),
            pid=d.get("pid"),
            role=d.get("role"),
            task=d.get("task"),
            started=d.get("started", 0),
        )

    def is_alive(self, probe):
        return bool(probe(self.pid if self.pid is not None else -1))

    def is_booting(self, now, max_boot):
        return self.task is None and (now - self.started) < max_boot
