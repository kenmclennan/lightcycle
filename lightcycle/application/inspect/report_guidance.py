import dataclasses
import datetime
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.guidance_library import GuidanceLibrary
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from lightcycle.domain.guidance.guidance import matches
from lightcycle.domain.guidance.retirement import (
    APPROVAL_UNKNOWN, Approval, COVERS_UNKNOWN, CoversResult, Thresholds, Usage, build_rows,
)
from lightcycle.domain.workflows.identity import parse_pin
from lightcycle.ports.github import ReadFailure
from lightcycle.ports.store import ProjectNotRegisteredError, ProjectResolutionError

_ISSUE_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/issues/\d+")


@dataclass(frozen=True)
class GuidanceReport:
    rows: Tuple = ()
    notes: Tuple[str, ...] = ()
    since: Optional[str] = None
    spawns: int = 0
    projects: Tuple = ()

    def as_dict(self):
        return {
            "window": {"since": self.since},
            "work": {"spawns": self.spawns, "projects": [dict(p) for p in self.projects]},
            "entries": [r.as_dict() for r in self.rows],
            "notes": list(self.notes),
        }


def parse_since(value):
    if value is None:
        return None
    if len(value) != 10:
        raise UseCaseError("--since must be a date in YYYY-MM-DD form, got %r" % value)
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise UseCaseError("--since must be a date in YYYY-MM-DD form, got %r" % value)
    return value


def _ids(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


class ReportGuidanceUseCase:
    def __init__(self, store, fs, git, github, config):
        self._store = store
        self._fs = fs
        self._git = git
        self._github = github
        self._config = config

    def _project(self, item):
        if item is None or not item.repo:
            return None
        try:
            return ProjectRegistry(self._store).find(item.repo)
        except (ProjectNotRegisteredError, ProjectResolutionError):
            return None

    def _usage(self, entries, since):
        known = {e.id for e in entries}
        deliveries, citations, last = {}, {}, {}
        all_deliveries, all_citations = {}, {}
        opportunity = {e.id: 0 for e in entries}
        spawns = 0
        work = {}
        for step in self._store.all_steps_including_done():
            records = {a.type: a.value for a in self._store.item_artifacts(step.id)
                       if a.type in ("guidance-delivered", "guidance-cited")}
            created = step.created_at
            for entry_id in _ids(records.get("guidance-delivered")):
                if entry_id not in known:
                    continue
                all_deliveries[entry_id] = all_deliveries.get(entry_id, 0) + 1
                if created and (entry_id not in last or created > last[entry_id]):
                    last[entry_id] = created
            for entry_id in _ids(records.get("guidance-cited")):
                if entry_id in known:
                    all_citations[entry_id] = all_citations.get(entry_id, 0) + 1
            if since is not None and (not created or created[:10] < since):
                continue
            for entry_id in _ids(records.get("guidance-delivered")):
                if entry_id in known:
                    deliveries[entry_id] = deliveries.get(entry_id, 0) + 1
            for entry_id in _ids(records.get("guidance-cited")):
                if entry_id in known:
                    citations[entry_id] = citations.get(entry_id, 0) + 1
            if "guidance-delivered" not in records:
                continue
            spawns += 1
            item = self._store.get_item(step.item)
            project = self._project(item)
            facets = project.facets if project else ()
            parsed = parse_pin(item.workflow) if item is not None else None
            origin = parsed[0] if parsed else None
            for entry in entries:
                if matches(entry, facets, step.stage, origin):
                    opportunity[entry.id] += 1
            if project is not None:
                key, registered = project.identity, True
            else:
                key, registered = (item.repo if item is not None else None) or None, False
            bucket = work.setdefault(
                (key, registered), {"facets": tuple(facets), "spawns": 0, "steps": {}})
            bucket["spawns"] += 1
            step_key = (step.stage, origin)
            bucket["steps"][step_key] = bucket["steps"].get(step_key, 0) + 1
        usage = {
            i: Usage(all_deliveries.get(i, 0), all_citations.get(i, 0), last.get(i))
            for i in known
        }
        window = {i: (deliveries.get(i, 0), citations.get(i, 0)) for i in known}
        return usage, window, opportunity, spawns, self._projects(work)

    def _projects(self, work):
        projects = []
        for (key, registered), bucket in work.items():
            steps = sorted(
                bucket["steps"].items(),
                key=lambda kv: (-kv[1], "%s/%s" % (kv[0][1] or "", kv[0][0] or "")))
            projects.append({
                "project": key,
                "registered": registered,
                "facets": list(bucket["facets"]),
                "spawns": bucket["spawns"],
                "steps": [{"stage": stage, "origin": origin, "count": n}
                          for (stage, origin), n in steps],
            })
        return tuple(sorted(projects, key=lambda p: (-p["spawns"], p["project"] or "")))

    def _covers(self, entries):
        results, notes = {}, []
        by_url = {}
        failure = None
        unreached = 0
        for entry in entries:
            if not entry.covers or entry.status == "deprecated":
                continue
            url = entry.covers
            if not _ISSUE_URL_RE.fullmatch(url):
                results[entry.id] = CoversResult(
                    COVERS_UNKNOWN, "covers is not a GitHub issue URL")
                continue
            if url not in by_url:
                if failure is not None:
                    by_url[url] = None
                else:
                    state = self._github.issue_state(url)
                    if isinstance(state, ReadFailure):
                        failure = state
                        by_url[url] = None
                    else:
                        by_url[url] = state
            state = by_url[url]
            if state is None:
                unreached += 1
                results[entry.id] = CoversResult(
                    COVERS_UNKNOWN, "covers-closed unknown: GitHub could not be read")
            elif state in ("OPEN", "CLOSED"):
                results[entry.id] = CoversResult(state)
            else:
                results[entry.id] = CoversResult(
                    COVERS_UNKNOWN, "covers issue state is %r" % state)
        if failure is not None:
            notes.append("covers-closed unknown for %d entries: GitHub unreachable (%s)" % (
                unreached, failure.stderr.strip() or "gh exited %d" % failure.returncode))
        return results, notes

    def _added(self, root, entries, usage):
        ref = GuidanceLibrary(self._git).ref(root)
        if ref is None:
            return {}
        return {
            e.id: self._git.added_at(root, ref, e.id + ".md")
            for e in entries
            if e.status == "stable" and usage[e.id].last_delivered is None
        }

    def _approvals(self, root, entries):
        ref = GuidanceLibrary(self._git).ref(root)
        if ref is None:
            return {}
        return {
            e.id: Approval.from_git(self._git.last_change_at(root, ref, e.id + ".md"))
            for e in entries
            if e.status == "stable"
        }

    def execute(self, now, since=None):
        project = self._store.get_project(GUIDANCE_WORKSPACE)
        if project is None or not project.local_path:
            raise UseCaseError("no guidance repo is registered")
        if not self._fs.exists(project.local_path):
            raise UseCaseError("guidance repo is missing at %s" % project.local_path)
        entries, problems = GuidanceLibrary(self._git).load(project.local_path)
        notes = ["%s: %s" % (name, reason) for name, reason in problems]
        usage, window, opportunity, spawns, projects = self._usage(entries, since)
        covers, covers_notes = self._covers(entries)
        thresholds = Thresholds(
            self._config.guidance_unused_after_deliveries(), self._config.guidance_dormant_days())
        moment = datetime.datetime.fromtimestamp(now).astimezone()
        added = self._added(project.local_path, entries, usage)
        approvals = self._approvals(project.local_path, entries)
        rows = [
            dataclasses.replace(
                r, deliveries=window[r.id][0], citations=window[r.id][1],
                notes=r.notes + (
                    ("approval unknown: git could not read history",)
                    if r.approval.state == APPROVAL_UNKNOWN else ()))
            for r in build_rows(
                entries, usage, thresholds, moment, covers, added, opportunity, approvals)
        ]
        return GuidanceReport(
            tuple(rows), tuple(notes + covers_notes), since, spawns, projects)
