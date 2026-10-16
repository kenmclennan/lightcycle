from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.application.work.resolve_shortcode import resolve_shortcode
from lightcycle.domain.work import ProjectIdentity
from lightcycle.ports.store import ProjectResolutionError
from lightcycle.domain.schedule.schedule import Schedule, merge_schedule
from lightcycle.domain.workflows.identity import format_pin, parse_pin

SCHEDULE_LABEL_PREFIX = "schedule:"


def schedule_label(schedule_id):
    return SCHEDULE_LABEL_PREFIX + schedule_id


@dataclass(frozen=True)
class ResolvedSchedule:
    schedule: Schedule
    problem: Optional[str] = None
    project_name: Optional[str] = None
    identity: Optional[str] = None
    shortcode: Optional[str] = None
    pin: Optional[str] = None


def _selector_of(workflow):
    pin = parse_pin(workflow)
    if pin is not None:
        return "%s/%s" % (pin[0], pin[1])
    return workflow


def _suggestion_of(flow, pin):
    meta = flow.workflow_meta(pin)
    suggestion = meta.get("schedule")
    return suggestion if isinstance(suggestion, dict) and suggestion else None


class ScheduleResolver:
    def __init__(self, store, config, flow, workflow_source):
        self._store = store
        self._config = config
        self._flow = flow
        self._workflow_source = workflow_source

    def resolve(self) -> List[ResolvedSchedule]:
        resolved = []
        covered = set()
        for schedule_id, block in self._config.schedule_blocks().items():
            workflow = block.get("workflow") or None
            if workflow:
                covered.add(_selector_of(workflow))
            resolved.append(self._resolve_block(schedule_id, block, workflow))
        resolved.extend(self._suggestions(covered))
        return resolved

    def _resolve_block(self, schedule_id, block, workflow):
        suggestion = None
        problem = None
        pin = None
        if workflow:
            try:
                pin = self._flow.resolve_selection(workflow)
                self._flow.load_graph(pin)
                suggestion = _suggestion_of(self._flow, pin)
            except ValueError as e:
                problem = "workflow %s does not resolve: %s" % (workflow, e)
        schedule = merge_schedule(schedule_id, block, suggestion, workflow=workflow)
        problem = schedule.problem or problem
        project_name = identity = shortcode = None
        if problem is None:
            try:
                project_name, identity, shortcode = self._resolve_project(schedule)
            except UseCaseError as e:
                problem = "project %s: %s" % (schedule.project, e)
        return ResolvedSchedule(
            schedule=schedule, problem=problem, project_name=project_name,
            identity=identity, shortcode=shortcode, pin=pin)

    def _resolve_project(self, schedule):
        if schedule.shortcode:
            try:
                registered = ProjectRegistry(self._store).find(schedule.project)
            except ProjectResolutionError as e:
                raise UseCaseError(str(e))
            return (ProjectIdentity.short_name(registered.identity), registered.identity,
                    schedule.shortcode)
        matched = resolve_shortcode(self._store, schedule.project)
        return matched.project, matched.identity, matched.value

    def _suggestions(self, covered):
        found = []
        for origin in self._workflow_source.list_origins():
            registry = self._workflow_source.read_registry(origin)
            sha = registry.current if registry else None
            if not sha:
                continue
            for name in sorted(self._workflow_source.workflow_names(origin, sha)):
                selector = "%s/%s" % (origin, name)
                if selector in covered:
                    continue
                try:
                    suggestion = _suggestion_of(self._flow, format_pin(origin, name, sha))
                except ValueError:
                    continue
                if suggestion is None:
                    continue
                schedule = merge_schedule(selector, None, suggestion, workflow=selector)
                found.append(ResolvedSchedule(
                    schedule=schedule, problem=schedule.problem,
                    pin=format_pin(origin, name, sha)))
        return found

    def bundle_suggestion_problems(self):
        problems = []
        for r in self._suggestions(set()):
            if r.problem:
                problems.append((r.schedule.id, r.problem))
        return problems

