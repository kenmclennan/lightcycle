from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple

_HOOK_OUTCOME_NAMES = ("pr_merge", "pr_conflict")


@dataclass(frozen=True)
class PlannedStep:
    stage: str
    kind: str
    outcome: Optional[str] = None
    hook: Optional[str] = None
    repeat_index: Optional[int] = None
    repeat_total: Optional[int] = None

    def key(self):
        if self.kind == "hook":
            return (self.kind, self.hook, self.stage, self.outcome)
        return (self.kind, self.stage, self.outcome)


@dataclass(frozen=True)
class PlannedWalk:
    steps: Tuple[PlannedStep, ...]

    def covered(self):
        return {s.key() for s in self.steps}


@dataclass(frozen=True)
class CoveragePlan:
    walks: Tuple[PlannedWalk, ...]


def _edge_transitions(graph):
    out = set()
    for stage, outs in (graph.edges or {}).items():
        for outcome, target in outs.items():
            if target:
                out.add(PlannedStep(stage=stage, kind="edge", outcome=outcome).key())
    return out


def _hook_transitions(graph):
    out = set()
    for name in _HOOK_OUTCOME_NAMES:
        for occ in graph.hook_occurrences(name):
            if len(occ) > 1:
                out.add(PlannedStep(stage=occ[0], kind="hook", hook=name, outcome=occ[1]).key())
    return out


def _feedback_occurrences(graph):
    return [
        (occ[0], occ[1]) for occ in graph.hook_occurrences("pr_feedback") if len(occ) > 1
    ]


def _cap_occurrences(graph):
    caps = []
    for occ in graph.hook_occurrences("ci_failed_cap"):
        if len(occ) > 3:
            caps.append(("edge", None, occ[0], occ[1], int(occ[2])))
    conflict_cap = {
        occ[0]: int(occ[1]) for occ in graph.hook_occurrences("pr_conflict_cap") if len(occ) > 1
    }
    conflict_outcome = {
        occ[0]: occ[1] for occ in graph.hook_occurrences("pr_conflict") if len(occ) > 1
    }
    for stage, n in conflict_cap.items():
        if stage in conflict_outcome:
            caps.append(("hook", "pr_conflict", stage, conflict_outcome[stage], n))
    return caps


def _outgoing(graph, stage):
    opts = []
    for outcome, target in sorted((graph.edges.get(stage) or {}).items()):
        if target:
            opts.append(PlannedStep(stage=stage, kind="edge", outcome=outcome))
    for name in _HOOK_OUTCOME_NAMES:
        for occ in graph.hook_occurrences(name):
            if occ[0] == stage and len(occ) > 1:
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


def _walk_from_entry(graph, entry, remaining, bound):
    still_open = set(remaining)
    steps = []
    stage = entry
    visited = set()
    n = 0
    while stage is not None and n < bound:
        n += 1
        visited.add(stage)
        options = _outgoing(graph, stage)
        if not options:
            break

        def score(opt):
            target = _target_of(graph, opt)
            in_remaining = opt.key() in still_open
            revisits = target in visited
            return (0 if in_remaining else 1, 1 if revisits else 0, opt.kind, opt.outcome or "")

        options.sort(key=score)
        chosen = options[0]
        steps.append(chosen)
        still_open.discard(chosen.key())
        stage = _target_of(graph, chosen)
    return PlannedWalk(tuple(steps))


def _forced_repeat_walk(graph, entry, stage, outcome, times, kind, hook=None):
    steps = []
    entry_path = _bfs_path(graph, entry, stage)
    if entry_path is None:
        return PlannedWalk(())
    steps.extend(entry_path)
    normal_target = (graph.edges.get(stage) or {}).get(outcome)
    for i in range(times):
        final = i == times - 1
        steps.append(
            PlannedStep(
                stage=stage, kind=kind, hook=hook, outcome=outcome,
                repeat_index=i + 1, repeat_total=times,
            )
        )
        if final:
            break
        if normal_target is None:
            break
        back = _bfs_path(graph, normal_target, stage)
        if back is None:
            break
        steps.extend(back)
    return PlannedWalk(tuple(steps))


def _feedback_walk(graph, entry, stage, feedback_step, bound):
    entry_path = _bfs_path(graph, entry, stage)
    if entry_path is None:
        return PlannedWalk(())
    steps = list(entry_path)
    steps.append(PlannedStep(stage=stage, kind="hook", hook="pr_feedback", outcome=feedback_step))
    resume = _walk_from_entry(graph, stage, set(), bound)
    steps.extend(resume.steps)
    return PlannedWalk(tuple(steps))


def build_coverage_plan(graph, flow):
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

    for kind, hook, stage, outcome, n in _cap_occurrences(graph):
        walks.append(_forced_repeat_walk(graph, entry, stage, outcome, n + 1, kind, hook=hook))

    for stage, feedback_step in _feedback_occurrences(graph):
        walks.append(_feedback_walk(graph, entry, stage, feedback_step, bound))

    return CoveragePlan(tuple(w for w in walks if w.steps))
