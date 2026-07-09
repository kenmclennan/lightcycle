from enum import StrEnum

from lightcycle.domain.work.lane import Lane


class State(StrEnum):
    BACKLOGGED = "backlogged"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    DONE = "done"


def lane_for(state, role):
    if state == State.DONE:
        return Lane.DONE
    if state == State.IN_PROGRESS:
        return Lane.ACTIVE
    if state == State.BACKLOGGED:
        return Lane.BLOCKED
    return Lane.INBOX if role == "human" else Lane.QUEUE
