from dataclasses import dataclass
from typing import Optional

ADMIT = "admit"
HOLD = "hold"

HELD_COMMENT_ORIGIN_LABEL = "held-comment-origin"

HELD = "held"
APPROVED = "approved"
REJECTED = "rejected"
DISPATCHED = "dispatched"

_TRANSITIONS = {
    HELD: (APPROVED, REJECTED),
    APPROVED: (DISPATCHED,),
}

KIND_INLINE = "inline"
KIND_REVIEW = "review"
KIND_MENTION = "mention"


def standing(author, trusted):
    who = author.casefold()
    if who in {t.casefold() for t in trusted}:
        return ADMIT
    return HOLD


def can_transition(current, target):
    return target in _TRANSITIONS.get(current, ())


def hold_key(kind, comment_id):
    return "%s:%s" % (kind, comment_id)


@dataclass(frozen=True)
class HeldComment:
    run_id: str
    key: str
    author: str
    body: str
    created_at: float
    path: Optional[str] = None
    line: Optional[int] = None
    state: str = HELD
    item_id: Optional[str] = None
    step_id: Optional[str] = None
    decided_at: Optional[str] = None
