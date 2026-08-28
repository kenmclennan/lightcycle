from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class LogKind(StrEnum):
    THINKING = "thinking"
    TEXT = "text"
    TOOL = "tool"
    RESULT = "result"
    SYSTEM = "system"
    RETRY = "retry"
    PROGRESS = "progress"
    UNPARSED = "unparsed"


@dataclass(frozen=True)
class LogLine:
    timestamp: datetime | None
    kind: LogKind
    text: str
