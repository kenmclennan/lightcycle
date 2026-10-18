from dataclasses import dataclass
from typing import Optional, Tuple

from lightcycle.domain.work.state import State

FOCUS_LOG = "log"
FOCUS_REASON = "reason"
FOCUS_PR = "pr"
FOCUS_DESCRIPTION = "description"
FOCUS_DETAIL = "detail"
FOCUS_CONTEXT = "context"
FOCUS_WORKFLOW = "workflow"
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
    presents_key: Optional[str] = None
    first_value_key: Optional[str] = None
    has_log: bool = False
    has_pr: bool = False
    has_reason: bool = False
    produced_outputs: Tuple[str, ...] = ()
    context_rows: int = 0
    parked: bool = False

    @property
    def detail_has_value(self):
        return self.first_value_key is not None


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


def _parked_entry(facts):
    return "reason" if facts.has_reason else "needs"


def _done(facts):
    if facts.has_pr:
        return StepFocus(FOCUS_DETAIL, "pr")
    if facts.produced_outputs:
        return StepFocus(FOCUS_CONTEXT, facts.produced_outputs[0])
    return None


def _fall_through(facts):
    if facts.detail_has_value:
        return StepFocus(FOCUS_DETAIL, facts.first_value_key)
    if facts.context_rows:
        return StepFocus(FOCUS_CONTEXT)
    return StepFocus(FOCUS_WORKFLOW)


def resolve_focus(facts) -> StepFocus:
    if facts.is_item:
        return StepFocus(FOCUS_DESCRIPTION)
    if facts.state == State.BLOCKED or (facts.state != State.DONE and facts.parked):
        return StepFocus(FOCUS_REASON, _parked_entry(facts))
    if facts.role == "human" and facts.state == State.WAITING and facts.presents_key:
        return StepFocus(FOCUS_DETAIL, facts.presents_key)
    if facts.state == State.RUNNING and facts.role != "engine":
        return StepFocus(FOCUS_LOG)
    if facts.role == "engine" and facts.state == State.QUEUED and facts.has_log:
        return StepFocus(FOCUS_LOG)
    if facts.state == State.DONE:
        done = _done(facts)
        if done is not None:
            return done
    return _fall_through(facts)
