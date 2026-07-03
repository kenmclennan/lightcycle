from enum import StrEnum


class Lane(StrEnum):
    INBOX = "inbox"
    ACTIVE = "active"
    QUEUE = "queue"
    BLOCKED = "blocked"
    DONE = "done"
