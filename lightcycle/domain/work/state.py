from enum import StrEnum

from lightcycle.domain.work.lane import Lane


class State(StrEnum):
    BACKLOGGED = "backlogged"
    BLOCKED = "blocked"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"


ALIASES = {State.RUNNING: "in_progress", State.WAITING: "ready"}


def lane_for(state):
    if state == State.DONE:
        return Lane.DONE
    if state == State.RUNNING:
        return Lane.ACTIVE
    if state == State.WAITING:
        return Lane.INBOX
    return Lane.QUEUE
