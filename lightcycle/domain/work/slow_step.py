import statistics
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from lightcycle.domain.work.node_id import node_id_key
from lightcycle.domain.work.state import State
from lightcycle.domain.work.step import Step

MIN_HISTORY = 20
P90_MULTIPLE = 2
FLOOR_SECONDS = 600
WAITING_TURN_RATE_FRACTION = 0.5


class SlowKind(StrEnum):
    WAITING = "waiting"
    WORKING = "working"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StageBaseline:
    stage: str
    p90_seconds: float
    median_turn_rate: Optional[float]
    history_size: int


@dataclass(frozen=True)
class SlowStep:
    step: Step
    active_seconds: float
    threshold_seconds: float
    kind: SlowKind
    baseline: StageBaseline


def turn_rate(step):
    return step.turn_count / (step.active_seconds / 60)


def _measured(step):
    return (
        step.state == State.DONE
        and step.stage is not None
        and step.active_seconds is not None
        and step.active_seconds > 0
    )


def _p90_excluding(sorted_values, value):
    n = len(sorted_values) - 1
    index = (9 * n + 9) // 10 - 1
    position = bisect_left(sorted_values, value)
    return sorted_values[index + 1 if index >= position else index]


def _median_turn_rate_excluding(stage_steps, excluded):
    rates = [turn_rate(s) for s in stage_steps if s.turn_count > 0 and s is not excluded]
    return statistics.median(rates) if rates else None


def _kind(step, median_rate):
    if step.turn_count == 0 or median_rate is None:
        return SlowKind.UNKNOWN
    if turn_rate(step) <= WAITING_TURN_RATE_FRACTION * median_rate:
        return SlowKind.WAITING
    return SlowKind.WORKING


def slow_steps(steps):
    by_stage = defaultdict(list)
    for step in steps:
        if _measured(step):
            by_stage[step.stage].append(step)

    found = []
    for stage, stage_steps in by_stage.items():
        if len(stage_steps) - 1 < MIN_HISTORY:
            continue
        durations = sorted(s.active_seconds for s in stage_steps)
        for step in stage_steps:
            p90 = _p90_excluding(durations, step.active_seconds)
            threshold = max(P90_MULTIPLE * p90, FLOOR_SECONDS)
            if step.active_seconds < threshold:
                continue
            median_rate = _median_turn_rate_excluding(stage_steps, step)
            found.append(SlowStep(
                step=step,
                active_seconds=step.active_seconds,
                threshold_seconds=threshold,
                kind=_kind(step, median_rate),
                baseline=StageBaseline(stage, p90, median_rate, len(stage_steps) - 1),
            ))
    found.sort(key=lambda s: (-s.active_seconds, node_id_key(s.step.id)))
    return found
