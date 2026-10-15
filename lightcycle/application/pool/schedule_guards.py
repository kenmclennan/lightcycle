import datetime
import re
from dataclasses import dataclass

from lightcycle.application.pool.daily_summary_cadence import _describe_day
from lightcycle.application.work.closed_count import closed_count
from lightcycle.application.work.pending_reflections import (
    item_reflection_count,
    pass_reflection_count,
)
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from lightcycle.domain.schedule.guards import (
    DAY_UNSUMMARISED,
    MATERIALS_CHANGED,
    PENDING_REFLECTIONS,
)
from lightcycle.domain.work import node_id_key, parse_timestamp
from lightcycle.ports.git import GitReadError
from lightcycle.ports.workflow_source import WorkflowSourceError

SCHEDULE_STATE_ARTIFACT = "schedule-state"

_DAY_STATE = re.compile(r"^day: (\d{4}-\d{2}-\d{2}) count: (\d+)$")
_BATCH_PREFIX = "batch: "


GUARD_FAILURES = (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RuntimeError)


class GuardUnreadable(Exception):
    pass


@dataclass(frozen=True)
class GuardResult:
    passed: bool
    detail: str
    title: str = ""
    description: str = ""
    state: str = ""


def _firing_states(store, firings):
    ordered = sorted(firings, key=lambda i: parse_timestamp(i.created_at))
    states = []
    for item in ordered:
        value = next(
            (a.value for a in store.item_artifacts(item.id) if a.type == SCHEDULE_STATE_ARTIFACT),
            None,
        )
        states.append((item, value))
    return states


class ScheduleGuards:
    def __init__(self, store, git, workflow_source):
        self._store = store
        self._git = git
        self._workflow_source = workflow_source

    def evaluate(self, guard, params, firings, now_local):
        states = _firing_states(self._store, firings)
        try:
            if guard == PENDING_REFLECTIONS:
                return self._pending_reflections(params["min"], states)
            if guard == MATERIALS_CHANGED:
                return self._materials_changed(states)
            if guard == DAY_UNSUMMARISED:
                return self._day_unsummarised(states, now_local)
        except (GitReadError, WorkflowSourceError, OSError) as e:
            raise GuardUnreadable("guard %s could not read its inputs: %s" % (guard, e))
        raise GuardUnreadable("guard %s is not one the engine has" % guard)

    def _pending_reflections(self, minimum, states):
        seen = set()
        for _item, value in states:
            if value and value.startswith(_BATCH_PREFIX):
                seen.update(p.strip() for p in value[len(_BATCH_PREFIX):].split(",") if p.strip())
        item_batch = [
            i for i in self._store.closed_unretroed_items()
            if i.id not in seen and item_reflection_count(self._store, i) > 0
        ]
        pass_batch = [
            p for p in self._store.closed_unretroed_passes()
            if p.id not in seen and pass_reflection_count(self._store, p) > 0
        ]
        pending = (
            sum(item_reflection_count(self._store, i) for i in item_batch)
            + sum(pass_reflection_count(self._store, p) for p in pass_batch)
        )
        detail = "%d pending reflections, needs %d" % (pending, minimum)
        if pending < minimum:
            return GuardResult(False, detail)
        ids = ", ".join(sorted([i.id for i in item_batch] + [p.id for p in pass_batch],
                               key=node_id_key))
        title = "Audit of %d closed items, %d closed passes" % (len(item_batch), len(pass_batch))
        return GuardResult(
            True, detail, title=title, description="batch: %s" % ids, state="batch: %s" % ids)

    def _fingerprint(self):
        parts = []
        for origin in self._workflow_source.list_origins():
            parts.append("%s=%s" % (origin, self._workflow_source.current_sha(origin)))
        project = self._store.get_project(GUIDANCE_WORKSPACE)
        if project is not None and project.local_path:
            ref = self._git.default_ref(project.local_path)
            sha = self._git.ref_sha(project.local_path, ref) if ref else None
            if sha:
                parts.append("%s=%s" % (GUIDANCE_WORKSPACE, sha))
        return ";".join(sorted(parts))

    def _materials_changed(self, states):
        fingerprint = self._fingerprint()
        last_item, last_state = states[-1] if states else (None, None)
        if last_item is not None and last_state == fingerprint:
            return GuardResult(False, "materials unchanged since %s" % last_item.id)
        since = parse_timestamp(last_item.created_at).date().isoformat() if last_item else "none"
        description = "materials: guidance, workflows\nsince: %s\nprevious: %s" % (
            since, last_item.id if last_item else "none")
        detail = "materials changed" if last_item else "materials never audited by this schedule"
        return GuardResult(
            True, detail, title="Audit of guidance and workflow bundles",
            description=description, state=fingerprint)

    def _day_unsummarised(self, states, now_local):
        today = now_local.date()
        recorded = {}
        for _item, value in states:
            match = _DAY_STATE.match(value or "")
            if match:
                day = match.group(1)
                recorded[day] = max(recorded.get(day, 0), int(match.group(2)))
        for day in (today, today - datetime.timedelta(days=1)):
            count = closed_count(self._store, day)
            row = self._store.day_summary(day)
            summarised = row.summarized_count if row else 0
            known = max(summarised, recorded.get(day.isoformat(), 0))
            if count > known:
                return GuardResult(
                    True, "%s has %d closes, %d summarised" % (day.isoformat(), count, known),
                    title="Daily summary: %s" % day.isoformat(),
                    description=_describe_day(self._store, day),
                    state="day: %s count: %d" % (day.isoformat(), count))
        return GuardResult(False, "every recent day is summarised")
