from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple

from lightcycle.domain.flow.hooks import (
    CI_FAILED_CAP,
    HOOK_MIN_ARITY,
    PR_CONFLICT,
    PR_CONFLICT_CAP,
    PR_CONFLICT_ESCALATE,
    PR_FEEDBACK,
    PR_MERGE,
    REVIEW_ROUNDS_CAP,
)

_HOOK_OUTCOME_NAMES = (PR_MERGE, PR_CONFLICT)


@dataclass(frozen=True)
class PlannedStep:
    stage: str
    kind: str
    outcome: Optional[str] = None
    hook: Optional[str] = None
    repeat_index: Optional[int] = None
    repeat_total: Optional[int] = None
    expected_phase: Optional[str] = None
    crosses_pass_end: bool = False

    def key(self):
        if self.kind == "hook":
            return (self.kind, self.hook, self.stage, self.outcome)
        return (self.kind, self.stage, self.outcome)


@dataclass(frozen=True)
class PlannedWalk:
    steps: Tuple[PlannedStep, ...]
    incomplete: bool = False
    stuck_at: Optional[str] = None

    def covered(self):
        return {s.key() for s in self.steps}


@dataclass(frozen=True)
class CoveragePlan:
    walks: Tuple[PlannedWalk, ...]


def _edge_transitions(graph):
    out = set()
    for stage, outs in (graph.edges or {}).items():
        mixed = any(outs.values())
        for outcome, target in outs.items():
            if target or (mixed and target is None):
                out.add(PlannedStep(stage=stage, kind="edge", outcome=outcome).key())
    return out


def _targetless_occurrences(graph):
    out = []
    for stage, outs in sorted((graph.edges or {}).items()):
        if not any(outs.values()):
            continue
        for outcome, target in sorted(outs.items()):
            if target is None:
                out.append((stage, outcome))
    return out


def _hook_transitions(graph):
    out = set()
    for name in _HOOK_OUTCOME_NAMES:
        for occ in graph.hook_occurrences(name):
            if len(occ) >= HOOK_MIN_ARITY[name]:
                out.add(PlannedStep(stage=occ[0], kind="hook", hook=name, outcome=occ[1]).key())
    return out


def _feedback_occurrences(graph):
    return [
        (occ[0], occ[1])
        for occ in graph.hook_occurrences(PR_FEEDBACK)
        if len(occ) >= HOOK_MIN_ARITY[PR_FEEDBACK]
    ]


def _cap_occurrences(graph, review_rounds_cap_n=None):
    caps = []
    for occ in graph.hook_occurrences(CI_FAILED_CAP):
        if len(occ) >= HOOK_MIN_ARITY[CI_FAILED_CAP]:
            caps.append(("edge", None, occ[0], occ[1], int(occ[2]), occ[3]))
    conflict_cap = {
        occ[0]: int(occ[1])
        for occ in graph.hook_occurrences(PR_CONFLICT_CAP)
        if len(occ) >= HOOK_MIN_ARITY[PR_CONFLICT_CAP]
    }
    conflict_outcome = {
        occ[0]: occ[1]
        for occ in graph.hook_occurrences(PR_CONFLICT)
        if len(occ) >= HOOK_MIN_ARITY[PR_CONFLICT]
    }
    conflict_escalate = {
        occ[0]: occ[1]
        for occ in graph.hook_occurrences(PR_CONFLICT_ESCALATE)
        if len(occ) >= HOOK_MIN_ARITY[PR_CONFLICT_ESCALATE]
    }
    for stage, n in conflict_cap.items():
        if stage in conflict_outcome:
            escalate_outcome = conflict_escalate.get(stage)
            escalate_target = (
                (graph.edges.get(stage) or {}).get(escalate_outcome)
                if escalate_outcome is not None else None
            )
            caps.append(("hook", PR_CONFLICT, stage, conflict_outcome[stage], n, escalate_target))
    if review_rounds_cap_n is not None:
        for occ in graph.hook_occurrences(REVIEW_ROUNDS_CAP):
            if len(occ) >= HOOK_MIN_ARITY[REVIEW_ROUNDS_CAP]:
                caps.append(("edge", None, occ[0], occ[1], review_rounds_cap_n, occ[2]))
    return caps


def _outgoing(graph, stage):
    opts = []
    for outcome, target in sorted((graph.edges.get(stage) or {}).items()):
        if target:
            opts.append(PlannedStep(stage=stage, kind="edge", outcome=outcome))
    for name in _HOOK_OUTCOME_NAMES:
        for occ in graph.hook_occurrences(name):
            if occ[0] == stage and len(occ) >= HOOK_MIN_ARITY[name]:
                target = (graph.edges.get(stage) or {}).get(occ[1])
                if target:
                    opts.append(PlannedStep(stage=stage, kind="hook", hook=name, outcome=occ[1]))
    return opts


def _target_of(graph, planned):
    return (graph.edges.get(planned.stage) or {}).get(planned.outcome)


def _bfs_path(graph, start, goal):
    if start == goal:
        return []
    q = deque([start])
    prev = {start: None}
    while q:
        cur = q.popleft()
        for outcome, target in sorted((graph.edges.get(cur) or {}).items()):
            if not target or target in prev:
                continue
            prev[target] = (cur, outcome)
            if target == goal:
                path = []
                node = target
                while prev[node] is not None:
                    p, o = prev[node]
                    path.append(PlannedStep(stage=p, kind="edge", outcome=o))
                    node = p
                path.reverse()
                return path
            q.append(target)
    return None


def _bfs_to_terminal(graph, start):
    q = deque([start])
    prev = {start: None}
    while q:
        cur = q.popleft()
        for outcome, target in sorted((graph.edges.get(cur) or {}).items()):
            if not target or target in prev:
                continue
            prev[target] = (cur, outcome)
            if not _outgoing(graph, target):
                path = []
                node = target
                while prev[node] is not None:
                    p, o = prev[node]
                    path.append(PlannedStep(stage=p, kind="edge", outcome=o))
                    node = p
                path.reverse()
                return path
            q.append(target)
    return None


def _walk_from_entry(graph, entry, remaining, bound):
    still_open = set(remaining)
    steps = []
    stage = entry
    visited = set()
    n = 0
    while n < bound:
        n += 1
        visited.add(stage)
        options = _outgoing(graph, stage)
        if not options:
            return PlannedWalk(tuple(steps))

        def score(opt):
            target = _target_of(graph, opt)
            in_remaining = opt.key() in still_open
            revisits = target in visited
            is_primary = graph.primary_outcome(stage) == opt.outcome
            return (
                0 if in_remaining else 1,
                1 if revisits else 0,
                0 if is_primary else 1,
                opt.kind,
                opt.outcome or "",
            )

        options.sort(key=score)
        chosen = options[0]
        steps.append(chosen)
        still_open.discard(chosen.key())
        stage = _target_of(graph, chosen)

    if not _outgoing(graph, stage):
        return PlannedWalk(tuple(steps))

    completion = _bfs_to_terminal(graph, stage)
    if completion is None:
        return PlannedWalk(tuple(steps), incomplete=True, stuck_at=stage)
    steps.extend(completion)
    return PlannedWalk(tuple(steps))


def _forced_repeat_walk(graph, entry, stage, outcome, times, kind, hook=None, escalate_target=None):
    steps = []
    entry_path = _bfs_path(graph, entry, stage)
    if entry_path is None:
        return PlannedWalk(())
    steps.extend(entry_path)
    normal_target = (graph.edges.get(stage) or {}).get(outcome)
    gate_phase = graph.phase_for(stage)
    phase_gated = kind == "edge" and hook is None
    reached_cap = False
    for i in range(times):
        final = i == times - 1
        steps.append(
            PlannedStep(
                stage=stage, kind=kind, hook=hook, outcome=outcome,
                repeat_index=i + 1, repeat_total=times,
                expected_phase=gate_phase if (final and phase_gated) else None,
            )
        )
        if final:
            reached_cap = True
            break
        if normal_target is None:
            break
        back = _bfs_path(graph, normal_target, stage)
        if back is None:
            break
        steps.extend(back)
    if reached_cap and escalate_target and _outgoing(graph, escalate_target):
        completion = _bfs_to_terminal(graph, escalate_target)
        if completion is None:
            return PlannedWalk(tuple(steps), incomplete=True, stuck_at=escalate_target)
        steps.extend(completion)
    return PlannedWalk(tuple(steps))


def _feedback_walk(graph, entry, stage, feedback_step, bound):
    entry_path = _bfs_path(graph, entry, stage)
    if entry_path is None:
        return PlannedWalk(())
    steps = list(entry_path)
    steps.append(
        PlannedStep(
            stage=stage, kind="hook", hook=PR_FEEDBACK, outcome=feedback_step,
            expected_phase=graph.phase_for(stage),
        )
    )
    resume = _walk_from_entry(graph, stage, set(), bound)
    steps.extend(resume.steps)
    return PlannedWalk(tuple(steps), incomplete=resume.incomplete, stuck_at=resume.stuck_at)


def _pass_end_hook(graph, stage, outcome):
    for name in _HOOK_OUTCOME_NAMES:
        for occ in graph.hook_occurrences(name):
            if len(occ) >= HOOK_MIN_ARITY[name] and occ[0] == stage and occ[1] == outcome:
                return name
    return None


def _pass_boundary_walk(graph, entry, stage, outcome, bound):
    entry_path = _bfs_path(graph, entry, stage)
    if entry_path is None:
        return PlannedWalk(())
    target = (graph.edges.get(stage) or {}).get(outcome)
    if target is None:
        return PlannedWalk(())
    hook = _pass_end_hook(graph, stage, outcome)
    steps = list(entry_path)
    steps.append(
        PlannedStep(
            stage=stage, kind="hook" if hook else "edge", hook=hook, outcome=outcome,
            crosses_pass_end=True,
        )
    )
    resume = _walk_from_entry(graph, target, set(), bound)
    steps.extend(resume.steps)
    return PlannedWalk(tuple(steps), incomplete=resume.incomplete, stuck_at=resume.stuck_at)


def _targetless_walk(graph, entry, stage, outcome):
    entry_path = _bfs_path(graph, entry, stage)
    if entry_path is None:
        return PlannedWalk(())
    steps = list(entry_path) + [PlannedStep(stage=stage, kind="edge", outcome=outcome)]
    return PlannedWalk(tuple(steps))


def build_coverage_plan(graph, flow, review_rounds_cap_n=None):
    entry = graph.entry
    remaining = set(_edge_transitions(graph)) | set(_hook_transitions(graph))

    bound = max(1, len(remaining)) * 4
    walks = []
    while remaining:
        walk = _walk_from_entry(graph, entry, remaining, bound)
        covered = walk.covered()
        before = len(remaining)
        remaining -= covered
        walks.append(walk)
        if len(remaining) == before:
            break

    for kind, hook, stage, outcome, n, escalate_target in _cap_occurrences(graph, review_rounds_cap_n):
        walks.append(
            _forced_repeat_walk(
                graph, entry, stage, outcome, n + 1, kind, hook=hook, escalate_target=escalate_target,
            )
        )

    for stage, feedback_step in _feedback_occurrences(graph):
        walks.append(_feedback_walk(graph, entry, stage, feedback_step, bound))

    for stage, outcome in sorted(graph.pass_ends):
        walks.append(_pass_boundary_walk(graph, entry, stage, outcome, bound))

    for stage, outcome in _targetless_occurrences(graph):
        walks.append(_targetless_walk(graph, entry, stage, outcome))

    return CoveragePlan(tuple(w for w in walks if w.steps))
