"""Worker: one spawned agent process (an entity)."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Worker:
    spawnid: Optional[str] = None
    pid: Optional[int] = None
    role: Optional[str] = None
    bead: Optional[str] = None
    started: float = 0

    @classmethod
    def from_state(cls, d) -> "Worker":
        return cls(spawnid=d.get("spawnid"), pid=d.get("pid"), role=d.get("role"),
                   bead=d.get("bead"), started=d.get("started", 0))

    def is_alive(self, probe):
        return bool(probe(self.pid if self.pid is not None else -1))

    def is_booting(self, now, max_boot):
        """Alive but not yet claimed (no bead) within the boot window - it already
        covers one ready task of its role, so the pool must not double-spawn."""
        return self.bead is None and (now - self.started) < max_boot
