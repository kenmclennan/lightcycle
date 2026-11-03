from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.guidance_library import GuidanceLibrary
from lightcycle.application.services.installed_agent_steps import InstalledAgentSteps
from lightcycle.config import ConfigError
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from lightcycle.domain.guidance.budget import heaviest_universal_step, is_universal, overflows
from lightcycle.domain.guidance.conventions import check_entries, is_checked_path
from lightcycle.ports.git import GitReadError
from lightcycle.ports.store import StoreUnreadableError


def _text(raw):
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


class CheckGuidanceUseCase:

    def __init__(self, git, fs, store, workflow_source, workflow_bundle, config):
        self._git = git
        self._fs = fs
        self._store = store
        self._workflow_source = workflow_source
        self._workflow_bundle = workflow_bundle
        self._config = config

    def execute(self, directory, mode, base):
        try:
            rows = self._git.changed_paths(directory, base)
        except GitReadError as e:
            raise UseCaseError(str(e))
        try:
            dirty = [p for p in self._git.uncommitted_paths(directory) if is_checked_path(p)]
        except GitReadError as e:
            raise UseCaseError(str(e))
        if dirty:
            return [
                "%s: uncommitted change - commit it first, guidance-check reads only committed work" % p
                for p in dirty
            ], 0, []
        changed, deleted = [], []
        for status, path in rows:
            if not is_checked_path(path):
                continue
            (deleted if status == "D" else changed).append(path)

        def read_head(path):
            raw = self._fs.read_bytes("%s/%s" % (directory, path))
            if raw is None:
                raise UseCaseError("cannot read %s in %s" % (path, directory))
            return _text(raw)

        def read_base(path):
            raw = self._git.read_file_at(directory, base, path)
            return None if raw is None else _text(raw)

        for path in deleted:
            if read_base(path) is None:
                raise UseCaseError("cannot read %s at %s in %s" % (path, base, directory))

        facet_pages = {
            rel.rsplit("/", 1)[-1][:-3]
            for rel in self._fs.list_files(directory)
            if rel.endswith(".md")
        }
        entry_ids = {
            rel[:-3]
            for rel in self._fs.list_files(directory)
            if is_checked_path(rel)
        }
        failures = check_entries(mode, changed, deleted, facet_pages, entry_ids, read_head, read_base)
        warnings = []
        if changed:
            more, notes = self._budget_lines(directory, base)
            failures = failures + more
            warnings = notes + self._universal_lines(directory, changed)
        return failures, len(changed), warnings

    def _universal_lines(self, directory, changed):
        try:
            budget = self._config.guidance_budget_bytes()
        except ConfigError:
            return []
        try:
            steps = InstalledAgentSteps(self._workflow_source, self._workflow_bundle, self._config).list()
        except OSError:
            steps = ()
        head_paths = [
            rel for rel in self._fs.list_files(directory)
            if not any(part.startswith(".") for part in rel.split("/"))
        ]
        entries, _ = GuidanceLibrary(self._git).load_files(
            head_paths, lambda rel: self._fs.read_bytes("%s/%s" % (directory, rel)))
        by_id = {e.id: e for e in entries}
        step, total = heaviest_universal_step(entries, steps)
        lines = []
        for path in changed:
            found = by_id.get(path[:-3])
            if found is None or not is_universal(found):
                continue
            if step is None:
                lines.append(
                    "warning: universal entries total %d of %d bytes; universal entry %s is %d bytes" % (
                        total, budget, found.id, found.size()))
            else:
                lines.append(
                    "warning: universal entry %s is %d bytes; step %s receives the most universal bytes, %d of %d" % (
                        found.id, found.size(), step, total, budget))
        return lines

    def _budget_lines(self, directory, base):
        try:
            budget = self._config.guidance_budget_bytes()
        except ConfigError as e:
            return [], ["budget check skipped: %s" % e]
        try:
            projects = [
                (p.identity, p.facets) for p in self._store.list_projects()
                if p.identity != GUIDANCE_WORKSPACE
            ]
            steps = InstalledAgentSteps(self._workflow_source, self._workflow_bundle, self._config).list()
        except (StoreUnreadableError, OSError) as e:
            return [], ["budget check skipped: %s" % e]
        if not projects or not steps:
            return [], []
        library = GuidanceLibrary(self._git)
        head_paths = [
            rel for rel in self._fs.list_files(directory)
            if not any(part.startswith(".") for part in rel.split("/"))
        ]
        head_entries, _ = library.load_files(
            head_paths, lambda rel: self._fs.read_bytes("%s/%s" % (directory, rel)))
        base_paths = self._git.list_files_at(directory, base)
        base_entries, _ = library.load_files(
            base_paths, lambda rel: self._git.read_file_at(directory, base, rel))
        before = {
            (o.project, o.step): set(o.skipped)
            for o in overflows(base_entries, projects, steps, budget)
        }
        failures, warnings = [], []
        for o in overflows(head_entries, projects, steps, budget):
            fresh = [i for i in o.skipped if i not in before.get((o.project, o.step), set())]
            if fresh:
                failures.append(
                    "budget: project %s, step %s: matched %d bytes against %d; "
                    "this change newly skips: %s" % (
                        o.project, o.step, o.matched_bytes, o.budget, ", ".join(fresh)))
            else:
                warnings.append(
                    "warning: project %s, step %s: matched %d bytes against %d; skipped: %s" % (
                        o.project, o.step, o.matched_bytes, o.budget, ", ".join(o.skipped)))
        return failures, warnings
