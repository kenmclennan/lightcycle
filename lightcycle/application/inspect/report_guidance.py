import datetime
import re
from dataclasses import dataclass
from typing import Tuple

from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.guidance_library import GuidanceLibrary
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from lightcycle.domain.guidance.retirement import (
    COVERS_UNKNOWN, CoversResult, Thresholds, Usage, build_rows,
)
from lightcycle.ports.github import ReadFailure

_ISSUE_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/issues/\d+")


@dataclass(frozen=True)
class GuidanceReport:
    rows: Tuple = ()
    notes: Tuple[str, ...] = ()

    def as_dict(self):
        return {"entries": [r.as_dict() for r in self.rows], "notes": list(self.notes)}


def _ids(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


class ReportGuidanceUseCase:
    def __init__(self, store, fs, git, github, config):
        self._store = store
        self._fs = fs
        self._git = git
        self._github = github
        self._config = config

    def _usage(self, known):
        deliveries, citations, last = {}, {}, {}
        for step in self._store.all_steps_including_done():
            records = {a.type: a.value for a in self._store.item_artifacts(step.id)
                       if a.type in ("guidance-delivered", "guidance-cited")}
            for entry_id in _ids(records.get("guidance-delivered")):
                if entry_id not in known:
                    continue
                deliveries[entry_id] = deliveries.get(entry_id, 0) + 1
                created = step.created_at
                if created and (entry_id not in last or created > last[entry_id]):
                    last[entry_id] = created
            for entry_id in _ids(records.get("guidance-cited")):
                if entry_id in known:
                    citations[entry_id] = citations.get(entry_id, 0) + 1
        return {
            i: Usage(deliveries.get(i, 0), citations.get(i, 0), last.get(i)) for i in known
        }

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

    def execute(self, now):
        project = self._store.get_project(GUIDANCE_WORKSPACE)
        if project is None or not project.local_path:
            raise UseCaseError("no guidance repo is registered")
        if not self._fs.exists(project.local_path):
            raise UseCaseError("guidance repo is missing at %s" % project.local_path)
        entries, problems = GuidanceLibrary(self._git).load(project.local_path)
        notes = ["%s: %s" % (name, reason) for name, reason in problems]
        usage = self._usage({e.id for e in entries})
        covers, covers_notes = self._covers(entries)
        thresholds = Thresholds(
            self._config.guidance_unused_after_deliveries(), self._config.guidance_dormant_days())
        moment = datetime.datetime.fromtimestamp(now).astimezone()
        rows = build_rows(entries, usage, thresholds, moment, covers)
        return GuidanceReport(tuple(rows), tuple(notes + covers_notes))
