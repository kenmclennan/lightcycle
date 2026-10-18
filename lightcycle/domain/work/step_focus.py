from dataclasses import dataclass
from typing import Optional, Tuple

from lightcycle.domain.work.state import State

FOCUS_LOG = "log"
FOCUS_REASON = "reason"
FOCUS_PR = "pr"
FOCUS_DESCRIPTION = "description"
FOCUS_DETAIL = "detail"
FOCUS_ARTIFACT = "artifact"
FOCUS_ARTIFACT_PREFIX = "artifact:"

PRESENTS_PR = "pr"
PRESENTS_DESCRIPTION = "description"


@dataclass(frozen=True)
class StepFocus:
    kind: str
    name: Optional[str] = None

    def __str__(self):
        if self.kind == FOCUS_ARTIFACT:
            return FOCUS_ARTIFACT_PREFIX + (self.name or "")
        return self.kind


@dataclass(frozen=True)
class FocusFacts:
    is_item: bool = False
    state: Optional[str] = None
    role: Optional[str] = None
    presents: Optional[str] = None
    produced: Tuple[str, ...] = ()
    has_log: bool = False
    artifact_types: frozenset = frozenset()
    has_pr: bool = False
    bare_detail: bool = False
    parked: bool = False


def parse_presents(value):
    if value is None:
        return None
    text = str(value).strip()
    if text in (PRESENTS_PR, PRESENTS_DESCRIPTION):
        return StepFocus(text)
    if text.startswith(FOCUS_ARTIFACT_PREFIX) and text[len(FOCUS_ARTIFACT_PREFIX):].strip():
        return StepFocus(FOCUS_ARTIFACT, text[len(FOCUS_ARTIFACT_PREFIX):].strip())
    return None


def presents_artifact(value):
    focus = parse_presents(value)
    return focus.name if focus is not None and focus.kind == FOCUS_ARTIFACT else None


def _fallback(facts):
    if facts.role == "human" and facts.bare_detail:
        return StepFocus(FOCUS_DESCRIPTION)
    return StepFocus(FOCUS_DETAIL)


def _presented(facts):
    focus = parse_presents(facts.presents)
    if focus is None:
        return None
    if focus.kind == FOCUS_ARTIFACT and focus.name not in facts.artifact_types:
        return None
    return focus


def _produced(facts):
    for atype in facts.produced:
        if atype == "pr":
            if facts.has_pr:
                return StepFocus(FOCUS_PR)
        elif atype in facts.artifact_types:
            return StepFocus(FOCUS_ARTIFACT, atype)
    return None


def resolve_focus(facts) -> StepFocus:
    if facts.is_item:
        return StepFocus(FOCUS_DESCRIPTION)
    if facts.state == State.BLOCKED or (facts.state != State.DONE and facts.parked):
        return StepFocus(FOCUS_REASON)
    if facts.role == "human" and facts.state == State.WAITING:
        presented = _presented(facts)
        if presented is not None:
            return presented
    if facts.state == State.RUNNING and facts.role != "engine":
        return StepFocus(FOCUS_LOG)
    if facts.role == "engine" and facts.state == State.QUEUED and facts.has_log:
        return StepFocus(FOCUS_LOG)
    if facts.state == State.DONE:
        return _produced(facts) or StepFocus(FOCUS_DETAIL)
    if facts.state == State.WAITING and facts.role == "human":
        return _fallback(facts)
    return StepFocus(FOCUS_DETAIL)
