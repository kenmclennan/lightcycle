from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class StepSpin:
    count: int
    since: float
    last_line: Optional[str] = None
    last_spawnid: Optional[str] = None


@dataclass(frozen=True)
class SpinLedger:
    steps: Dict[str, StepSpin] = field(default_factory=dict)
    pool_streak: int = 0
    pool_tripped: bool = False

    @classmethod
    def from_state(cls, d) -> "SpinLedger":
        raw_steps = d.get("steps") or {}
        steps = {
            step_id: StepSpin(
                count=entry.get("count", 0), since=entry.get("since"),
                last_line=entry.get("last_line"), last_spawnid=entry.get("last_spawnid"),
            )
            for step_id, entry in raw_steps.items()
        }
        pool = d.get("pool") or {}
        return cls(
            steps=steps,
            pool_streak=pool.get("streak", 0),
            pool_tripped=pool.get("tripped", False),
        )

    def as_dict(self) -> dict:
        return {
            "steps": {
                step_id: {
                    "count": e.count, "since": e.since, "last_line": e.last_line,
                    "last_spawnid": e.last_spawnid,
                }
                for step_id, e in self.steps.items()
            },
            "pool": {"streak": self.pool_streak, "tripped": self.pool_tripped},
        }

    def entry(self, step) -> Optional[StepSpin]:
        return self.steps.get(step)

    def record_activity(self, step) -> "SpinLedger":
        if step not in self.steps:
            return self
        steps = dict(self.steps)
        del steps[step]
        return SpinLedger(steps=steps, pool_streak=self.pool_streak, pool_tripped=self.pool_tripped)

    def clear(self, step) -> "SpinLedger":
        return self.record_activity(step)

    def record_death(self, step, now, last_line, spawnid=None) -> "SpinLedger":
        prior = self.steps.get(step)
        if prior is not None and prior.last_spawnid == spawnid:
            return self
        count = (prior.count if prior else 0) + 1
        since = prior.since if prior else now
        steps = dict(self.steps)
        steps[step] = StepSpin(count=count, since=since, last_line=last_line, last_spawnid=spawnid)
        return SpinLedger(steps=steps, pool_streak=self.pool_streak, pool_tripped=self.pool_tripped)

    def should_park(self, step, cap) -> bool:
        entry = self.steps.get(step)
        return entry is not None and entry.count >= cap

    def advance_pool(self, rejected, dead_with_step, no_work_with_step, saw_real_activity, cap):
        streak = self.pool_streak
        tripped = self.pool_tripped
        if not rejected and dead_with_step >= 2 and no_work_with_step == dead_with_step:
            streak += 1
        elif saw_real_activity:
            streak = 0
            tripped = False
        spin_opened = False
        if not tripped and streak >= cap:
            tripped = True
            spin_opened = True
        new_ledger = SpinLedger(steps=self.steps, pool_streak=streak, pool_tripped=tripped)
        return new_ledger, tripped, spin_opened
