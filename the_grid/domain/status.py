"""Status: the lifecycle state of a task (a value object).

A StrEnum so it is type-safe and enumerable, yet still equal to and serialises as
its string value - existing `status == "ready"` comparisons and JSON views are
unchanged.
"""
from enum import StrEnum


class Status(StrEnum):
    READY = "ready"
    IN_PROGRESS = "in-progress"
    NEEDS_HUMAN = "needs-human"
    DONE = "done"
