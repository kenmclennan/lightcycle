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
