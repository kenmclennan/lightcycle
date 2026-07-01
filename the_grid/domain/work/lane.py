"""Lane: the board column a task displays in (a value object).

The `tg status` board is a kanban; each Lane is one of its columns. A StrEnum so
its value is the display label directly - no separate key/label mapping. Most lanes
are a projection of Status (see Status.lane); BLOCKED is sourced from readiness
(see TaskQueue.by_lane).
"""
from enum import StrEnum


class Lane(StrEnum):
    INBOX = "inbox"
    ACTIVE = "active"
    QUEUE = "queue"
    BLOCKED = "blocked"
    DONE = "done"
