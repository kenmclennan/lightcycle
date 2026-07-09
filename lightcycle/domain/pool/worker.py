from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Worker:
    spawnid: Optional[str] = None
    pid: Optional[int] = None
    role: Optional[str] = None
    step: Optional[str] = None
    started: float = 0
    pid_started: Optional[str] = None
    log: Optional[str] = None
    checked: bool = False

    @classmethod
    def from_state(cls, d) -> "Worker":
        return cls(
            spawnid=d.get("spawnid"),
            pid=d.get("pid"),
            role=d.get("role"),
            step=d.get("step"),
            started=d.get("started", 0),
            pid_started=d.get("pid_started"),
            log=d.get("log"),
            checked=bool(d.get("checked", False)),
        )

    def is_alive(self, probe):
        return bool(probe(self.pid if self.pid is not None else -1, self.pid_started))

    def is_booting(self, now, max_boot):
        return self.step is None and (now - self.started) < max_boot
