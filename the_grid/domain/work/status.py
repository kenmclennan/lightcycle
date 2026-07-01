"""Status: the lifecycle state of a task (a value object).

A StrEnum so it is type-safe and enumerable, yet still equal to and serialises as
its string value - existing `status == "ready"` comparisons and JSON views are
unchanged.
"""
from enum import StrEnum

from the_grid.domain.work.lane import Lane


class Status(StrEnum):
    READY = "ready"
    IN_PROGRESS = "in-progress"
    NEEDS_HUMAN = "needs-human"
    DONE = "done"

    @property
    def lane(self) -> Lane:
        return _LANES[self]


_LANES = {
    Status.NEEDS_HUMAN: Lane.INBOX,
    Status.IN_PROGRESS: Lane.ACTIVE,
    Status.READY: Lane.QUEUE,
    Status.DONE: Lane.DONE,
}
