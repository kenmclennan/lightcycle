import datetime
import os
import re
from dataclasses import dataclass
from typing import Dict, List

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.engine_steps import LIFECYCLE_ORIGIN_LABEL
from lightcycle.application.pool.schedule_resolution import ScheduleResolver
from lightcycle.application.services.flow import FlowService
from lightcycle.application.workflows.engine_requirement_check import bundle_conflict_messages
from lightcycle.application.workflows.pin_drift import PinDrift
from lightcycle.application.workflows.lifecycle import (
    directory_lifecycle,
    directory_lifecycle_problems,
)
from lightcycle.application.services.guidance_library import NO_REF_ENTRY, GuidanceLibrary
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE, LEGACY_KNOWLEDGE_WORKSPACE
from lightcycle.config import ConfigError
from lightcycle.domain.guidance.guidance import ENTRY, classify, fill, matches_project, matches_step_key, order
from lightcycle.domain.guidance.conventions import (
    CONVENTIONS_VERSION, SKIPPED_NAMES, check_entries,
)
from lightcycle.frontmatter import split_frontmatter
from lightcycle.ports.git import GitReadError
from lightcycle.domain.health import (
    Problem, blank_key_fix, fsck, obsolete_key_fix, schedule_not_enabled_fix,
)
from lightcycle.domain.schedule.guards import RETIRED_JOB_SCHEDULES
from lightcycle.domain.schedule.schedule import SOURCE_BUNDLE
from lightcycle.application.workflows.script_tooling import WorkflowScripts
from lightcycle.domain.work.run_log import latest_log_path
from lightcycle.domain.work.state import State
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT, contract_compatible
from lightcycle.domain.workflows.identity import format_pin, parse_pin
from lightcycle.domain.workflows.lifecycle import missing_required_keys
from lightcycle.domain.workflows.source import parse_source_manifest


CONVENTIONS_FILE = "CONVENTIONS.md"
REVERT_HISTORY_LIMIT = 200
_VERSION_LINE = re.compile(r"^Conventions version:\s*(\d+)\s*$")


@dataclass(frozen=True)
class DoctorInput:
    pass


@dataclass(frozen=True)
class DoctorReport:
    problems: Dict[str, List[Problem]]

    def healthy(self) -> bool:
        return not any(self.problems.values())


class DoctorUseCase:
    def __init__(
        self, store, workflow_source, config, workflow_bundle, fs, machine, worktrees,
        git, guidance_sync_status, config_reload_status, lock,
    ):
        self._store = store
        self._workflow_source = workflow_source
        self._config = config
        self._workflow_bundle = workflow_bundle
        self._fs = fs
        self._machine = machine
        self._worktrees = worktrees
        self._git = git
        self._guidance_sync_status = guidance_sync_status
        self._config_reload_status = config_reload_status
        self._lock = lock
        self._pin_drift = PinDrift(workflow_source, workflow_bundle, config)
        self._schedule_resolver = ScheduleResolver(
            store, config, FlowService(workflow_bundle, store, config, workflow_source),
            workflow_source)

    def execute(self, input: DoctorInput) -> DoctorReport:
        nodes = self._store.all_nodes_including_done()
        pins, contracts = self._bundle_problems(nodes)
        lifecycle_contract, lifecycle_config = self._lifecycle_problems()
        contracts = (
            contracts + self._requirement_problems() + self._suggestion_problems()
            + lifecycle_contract)
        return DoctorReport(problems={
            "store": fsck(nodes),
            "pins": pins,
            "contract": contracts,
            "origin": self._origin_problems() + self._hook_failure_problems(),
            "config": (
                self._config_problems() + self._retired_job_problems()
                + self._schedule_problems() + self._reload_problems() + lifecycle_config),
            "orphans": self._orphan_problems(),
            "facets": self._guidance_registration_problems() + self._facet_problems(),
            "guidance": self._guidance_problems() + self._guidance_shortcode_problems(),
        })

    def _in_flight_pins(self, nodes):
        for n in nodes:
            if n.type != "item" or n.state == State.DONE:
                continue
            parsed = parse_pin(n.workflow)
            if parsed:
                yield n, parsed

    def _open_steps(self, item_id):
        return [
            (s.stage or s.role, s.state == State.RUNNING)
            for s in self._store.children(item_id)
            if s.type == "step" and s.state != State.DONE
        ]

    def _bundle_problems(self, nodes):
        pins, contracts = [], []
        for n, (origin, name, sha) in self._in_flight_pins(nodes):
            pin = format_pin(origin, name, sha)
            if not self._workflow_source.has_version(origin, sha):
                pins.append(Problem("pins", "pinned bundle %s no longer resolves on disk" % pin, n.id))
                continue
            bundle = self._workflow_source.pinned_bundle(origin, sha)
            manifest = parse_source_manifest(self._workflow_source.read_manifest(bundle))
            if not contract_compatible(manifest.contract):
                contracts.append(Problem(
                    "contract",
                    "%s has contract %d, engine is %d" % (pin, manifest.contract, ENGINE_CONTRACT),
                    n.id,
                ))
            current = self._workflow_source.current_sha(origin)
            if current and current != sha and self._workflow_source.has_version(origin, current):
                try:
                    changed = self._pin_drift.changed_steps_ahead(
                        self._open_steps(n.id), origin, name, sha, current)
                except ValueError as e:
                    pins.append(Problem(
                        "pins",
                        "%s cannot be compared with origin's current %s: %s" % (
                            pin, format_pin(origin, name, current), e),
                        n.id,
                    ))
                    continue
                if changed:
                    pins.append(Problem(
                        "pins",
                        "%s differs from origin's current %s (changed steps: %s)" % (
                            pin, format_pin(origin, name, current), ", ".join(sorted(changed))),
                        n.id,
                    ))
        return pins, contracts

    def _lifecycle_problems(self):
        contract, config = [], []
        blocks = {}
        for origin in self._workflow_source.list_origins():
            registry = self._workflow_source.read_registry(origin)
            if registry is None or not registry.current:
                continue
            if not self._workflow_source.has_version(origin, registry.current):
                continue
            directory = self._workflow_source.pinned_bundle(origin, registry.current)
            for name in self._workflow_source.workflow_names(origin, registry.current):
                block = self._config.workflow_config_block_name(origin, name)
                blocks.setdefault(block, []).append("%s/%s" % (origin, name))
                for message in directory_lifecycle_problems(
                        self._workflow_bundle, self._fs, directory, name):
                    contract.append(Problem("contract", "%s/%s: %s" % (origin, name, message)))
                for message in WorkflowScripts(self._workflow_bundle, self._fs).problems(
                        directory, name):
                    contract.append(Problem("contract", "%s/%s: %s" % (origin, name, message)))
                declared, _ = directory_lifecycle(self._workflow_bundle, directory, name)
                if declared is None:
                    continue
                values = self._config.workflow_config(origin, name)
                for key in missing_required_keys(declared, values):
                    config.append(Problem(
                        "config",
                        "workflow %s/%s needs config key %r in block %r, which is missing or blank"
                        % (origin, name, key, block)))
        for block, owners in sorted(blocks.items()):
            if len(owners) > 1:
                config.append(Problem(
                    "config",
                    "workflows %s all map to the config block %r" % (", ".join(owners), block)))
        return contract, config

    def _requirement_problems(self):
        problems = []
        engine_version = self._config.version()
        for origin, sha, manifest_text in bundle_conflict_messages(self._workflow_source):
            try:
                requirement = parse_source_manifest(manifest_text).requires_engine
            except ValueError as e:
                problems.append(Problem(
                    "contract", "origin %s bundle %s has a malformed manifest: %s" % (origin, sha, e)))
                continue
            if requirement is not None and not requirement.satisfied_by(engine_version):
                problems.append(Problem(
                    "contract",
                    "origin %s bundle %s requires engine %s, engine is %s"
                    % (origin, sha, requirement.describe(), engine_version)))
        return problems

    def _origin_problems(self):
        problems = []
        if "default-origin" not in self._config.missing_config_keys():
            origin = self._config.default_origin()
            if self._workflow_source.current_sha(origin) is None:
                problems.append(
                    Problem("origin", "default-origin %r is set but has no pulled bundle" % origin))
        for name in self._workflow_source.list_origins():
            registry = self._workflow_source.read_registry(name)
            reason = self._workflow_source.unresolvable_reason(
                registry.url if registry else None, registry.ref if registry else None)
            if reason:
                problems.append(Problem("origin", "%s: %s" % (name, reason)))
        return problems

    def _hook_failure_problems(self):
        problems = []
        for item in self._store.items_with_label(LIFECYCLE_ORIGIN_LABEL):
            if item.state == State.DONE:
                continue
            log = latest_log_path(self._store.item_artifacts(item.id))
            where = "log %s" % log if log else "no log recorded"
            problems.append(Problem(
                "origin", "open maintenance failure %s (%s): %s" % (item.id, item.title, where),
                node_id=item.id))
        return problems

    def _config_problems(self):
        missing = self._config.missing_config_keys()
        settings = self._config.resolved_settings()
        problems = [
            Problem("config", "required config key %r is not set" % k) for k in missing
        ]
        problems += [
            Problem(
                "config", "required config key %r is set but blank" % s.key,
                kind="config-key-blank", fix=blank_key_fix(s.key),
            )
            for s in settings
            if s.state == "unset" and s.key not in missing
        ]
        problems += [
            Problem("config", "required config key %r is set but rejected: %s" % (s.key, s.error))
            for s in settings
            if s.state == "invalid"
        ]
        problems += [
            Problem(
                "config", "config key %r is set but not read by this version" % k,
                kind="config-key-obsolete", fix=obsolete_key_fix(k),
            )
            for k in self._config.obsolete_config_keys()
        ]
        return problems

    def _reload_problems(self):
        if self._config_reload_status is None or self._lock is None:
            return []
        state = self._config_reload_status.load()
        holder = self._lock.holder_pid()
        if holder is None or state.get("pid") != holder:
            return []
        problems = []
        if (state.get("outcome") == "rejected"
                and state.get("rejected_mtime") == self._config.config_mtime()):
            problems.append(Problem(
                "config",
                "config edit rejected by the running pool (%s); it is running on the last good "
                "config" % state.get("reason")))
        restart = state.get("restart_required") or []
        if restart:
            problems.append(Problem(
                "config", "running pool needs a restart for: %s" % ", ".join(restart)))
        return problems

    def _retired_job_problems(self):
        retired = {selector for _id, selector in RETIRED_JOB_SCHEDULES}
        return [
            Problem(
                "config",
                "workflow %s has no schedule block in config; the engine no longer runs this "
                "job itself" % r.schedule.workflow,
                kind="schedule-not-enabled", fix=schedule_not_enabled_fix(r.schedule.workflow),
            )
            for r in self._schedule_resolver.resolve()
            if r.schedule.source == SOURCE_BUNDLE and r.schedule.workflow in retired
        ]

    def _schedule_problems(self):
        return [
            Problem("config", "schedule %s: %s" % (r.schedule.id, r.problem))
            for r in self._schedule_resolver.resolve()
            if r.schedule.enabled and r.problem
        ]

    def _suggestion_problems(self):
        return [
            Problem("contract", "schedule %s: %s" % (sid, problem))
            for sid, problem in self._schedule_resolver.bundle_suggestion_problems()
        ]

    def _expected_worktree_paths(self):
        expected = set()
        for step in self._store.claimed_steps():
            try:
                expected.add(self._worktrees.worktree_path(step))
            except UseCaseError:
                continue
        return expected

    def _guidance_registration_problems(self):
        if (
            self._store.get_project(LEGACY_KNOWLEDGE_WORKSPACE) is None
            or self._store.get_project(GUIDANCE_WORKSPACE) is None
        ):
            return []
        return [Problem(
            "facets",
            "projects %s and %s are both registered; %s is the guidance repo - check the "
            "path of %s, then run `lc project rm %s`"
            % (
                LEGACY_KNOWLEDGE_WORKSPACE, GUIDANCE_WORKSPACE, GUIDANCE_WORKSPACE,
                LEGACY_KNOWLEDGE_WORKSPACE, LEGACY_KNOWLEDGE_WORKSPACE,
            ),
        )]

    def _concept_pages(self, root):
        return {
            name[: -len(".md")]
            for name in (f.rsplit("/", 1)[-1] for f in GuidanceLibrary(self._git).files(root))
            if name.endswith(".md") and name != "index.md"
        }

    def _guidance_shortcode_problems(self):
        repo = self._store.get_project(GUIDANCE_WORKSPACE)
        if repo is None or repo.shortcode:
            return []
        try:
            shortcode = self._config.guidance_shortcode()
        except ConfigError:
            return []
        return [Problem(
            "guidance",
            "the guidance project has no id shortcode, so --project guidance is refused and "
            "guidance items take a product project's prefix",
            kind="guidance-shortcode-missing",
            fix="run lc project set %s --shortcode %s" % (GUIDANCE_WORKSPACE, shortcode),
        )]

    def _guidance_problems(self):
        repo = self._store.get_project(GUIDANCE_WORKSPACE)
        if repo is None or not repo.local_path or not self._fs.exists(repo.local_path):
            return []
        library = GuidanceLibrary(self._git)
        entries, unreadable = library.load(repo.local_path)
        problems = self._fetch_problems(library, repo.local_path)
        problems += [
            Problem(
                "guidance",
                "entry %s cannot be delivered: %s - fix its front matter in the guidance repo"
                % (name, reason),
            )
            for name, reason in unreadable
            if name != NO_REF_ENTRY
        ]
        pages = self._concept_pages(repo.local_path)
        for entry in entries:
            for facet in entry.facets:
                if facet not in pages:
                    problems.append(Problem(
                        "guidance",
                        "entry %s applies to facet %s but the guidance repo has no concept "
                        "page for it - add %s.md under the guidance repo, or remove the facet "
                        "from the entry" % (entry.id, facet, facet),
                    ))
        problems += self._reverted_problems(library, repo.local_path, entries)
        problems += self._budget_problems([e for e in entries if e.is_candidate()])
        problems += self._conventions_problems(library, repo.local_path)
        problems += self._nonconforming_problems(library, repo.local_path, entries, unreadable, pages)
        return problems

    def _reverted_problems(self, library, root, entries):
        ref = library.ref(root)
        if ref is None:
            return []
        problems = []
        for entry in entries:
            if entry.status != "draft":
                continue
            path = entry.id + ".md"
            try:
                commits = self._git.commits_touching(root, ref, path, REVERT_HISTORY_LIMIT)
            except GitReadError as e:
                problems.append(Problem(
                    "guidance",
                    "history of entry %s cannot be read: %s" % (entry.id, e),
                ))
                continue
            reverting = self._reverting_commit(root, path, commits)
            if reverting is not None:
                problems.append(Problem(
                    "guidance",
                    "entry %s was stable and is draft since commit %s, so it is no longer delivered"
                    % (entry.id, reverting[:12]),
                    kind="guidance-entry-reverted",
                    fix="file a `guidance-entry` item to restore %s to stable" % entry.id,
                ))
        return problems

    def _reverting_commit(self, root, path, commits):
        newer = None
        for sha in commits:
            raw = self._git.read_file_at(root, sha, path)
            if raw is None:
                newer = None
                continue
            meta, body = split_frontmatter(raw.decode("utf-8", errors="replace"))
            result = classify(path[: -len(".md")], meta, body)
            if result.kind != ENTRY:
                continue
            if result.entry.status == "stable":
                return newer
            newer = sha
        return None

    def _conventions_problems(self, library, root):
        ref = library.ref(root)
        if ref is None:
            return []
        recorded = 0
        if CONVENTIONS_FILE in library.files(root):
            raw = self._git.read_file_at(root, ref, CONVENTIONS_FILE)
            try:
                text = raw.decode("utf-8") if raw is not None else None
            except UnicodeDecodeError:
                text = None
            if text is None:
                return [Problem(
                    "guidance",
                    "%s cannot be read at %s - check the guidance repo" % (CONVENTIONS_FILE, ref),
                )]
            for line in text.splitlines():
                match = _VERSION_LINE.match(line.strip())
                if match:
                    recorded = int(match.group(1))
                    break
        if recorded >= CONVENTIONS_VERSION:
            return []
        return [Problem(
            "guidance",
            "guidance repo conventions are version %d, engine ships version %d"
            % (recorded, CONVENTIONS_VERSION),
            kind="guidance-conventions-outdated",
            fix="update %s to version %d by PR on the guidance repo (`lc guidance-conventions` prints "
            "the text); file a `guidance-entry` item to carry it" % (CONVENTIONS_FILE, CONVENTIONS_VERSION),
        )]

    def _nonconforming_problems(self, library, root, entries, unreadable, pages):
        ref = library.ref(root)
        if ref is None:
            return []
        paths = sorted(
            [e.id + ".md" for e in entries]
            + [name + ".md" for name, _ in unreadable if name != NO_REF_ENTRY]
        )

        def read_head(path):
            raw = self._git.read_file_at(root, ref, path)
            return "" if raw is None else raw.decode("utf-8", errors="replace")

        failing = [
            path for path in paths
            if path.rsplit("/", 1)[-1] not in SKIPPED_NAMES
            and check_entries("final", [path], [], pages, read_head, lambda p: None)
        ]
        if not failing:
            return []
        named = ", ".join(failing[:5])
        if len(failing) > 5:
            named += " and %d more" % (len(failing) - 5)
        return [Problem(
            "guidance",
            "%d guidance entries fail the current conventions: %s" % (len(failing), named),
            kind="guidance-entries-nonconforming",
            fix="file a `guidance-entry` item to backfill them",
        )]

    def _fetch_problems(self, library, root):
        problems = []
        status = self._guidance_sync_status.load()
        if status and not status.get("ok", True):
            ref = status.get("ref")
            reading = (
                "delivery is reading the last fetched ref %s" % ref if ref
                else "delivery has no fetched ref to read"
            )
            at = datetime.datetime.fromtimestamp(status.get("at", 0)).astimezone()
            problems.append(Problem(
                "guidance",
                "guidance repo fetch failed at %s: %s - %s"
                % (at.strftime("%Y-%m-%d %H:%M:%S"), status.get("detail", ""), reading),
            ))
        if library.ref(root) is None and library.has_origin(root):
            problems.append(Problem(
                "guidance",
                "guidance repo has never been fetched - delivery has nothing to read until "
                "the pool ticks",
            ))
        return problems

    def _budget_problems(self, candidates):
        try:
            budget = self._config.guidance_budget_bytes()
        except ConfigError:
            return []
        problems = []
        for project in self._store.list_projects():
            if project.identity == GUIDANCE_WORKSPACE:
                continue
            local = [e for e in candidates if matches_project(e, project.facets)]
            keys = sorted({name for e in local for name in e.steps})
            for key in [None] + keys:
                _, skipped = fill(order([e for e in local if matches_step_key(e, key)]), budget)
                if skipped:
                    problems.append(Problem(
                        "guidance",
                        "project %s: entries for %s exceed guidance-budget-bytes (%d) and would "
                        "be skipped: %s - shorten them or raise the budget" % (
                            project.identity, key or "any step", budget,
                            ", ".join(e.id for e in skipped)),
                    ))
        return problems

    def _facet_problems(self):
        declaring = [p for p in self._store.list_projects() if p.facets]
        if not declaring:
            return []
        repo = self._store.get_project(GUIDANCE_WORKSPACE)
        if repo is None or not repo.local_path:
            return [Problem(
                "facets",
                "facets are declared but no guidance repo is registered - run `lc init`",
            )]
        if not self._fs.exists(repo.local_path):
            return [Problem(
                "facets",
                "facets are declared but the guidance repo is missing at %s - restore it, "
                "or run `lc project rm %s` then `lc init`" % (repo.local_path, GUIDANCE_WORKSPACE),
            )]
        pages = self._concept_pages(repo.local_path)
        problems = []
        for project in declaring:
            for facet in project.facets:
                if facet not in pages:
                    problems.append(Problem(
                        "facets",
                        "project %s declares facet %s but the guidance repo has no concept "
                        "page for it - add %s.md under the guidance repo, or remove the facet "
                        "with `lc project set %s --facets <remaining>`"
                        % (project.identity, facet, facet, project.identity),
                    ))
        return problems

    def _orphan_problems(self):
        expected = self._expected_worktree_paths()
        problems = []
        for project in self._store.list_projects():
            if not project.local_path:
                continue
            wt_dir = self._fs.worktrees_dir(project.local_path)
            existing = set(self._fs.list_dir(wt_dir))
            for name in existing:
                path = os.path.join(wt_dir, name)
                if path in expected:
                    continue
                pids = self._machine.worktree_pids(path)
                if not pids:
                    continue
                problems.append(Problem(
                    "orphans",
                    "worktree %s has no active worker but %d live process(es): %s" % (
                        path, len(pids), ", ".join(str(p) for p in pids)),
                ))
            problems += self._deleted_worktree_problems(wt_dir, existing)
        return problems

    def _deleted_worktree_problems(self, wt_dir, existing):
        by_worktree = {}
        for cwd, pids in self._machine.cwd_pids_under(wt_dir).items():
            name = os.path.relpath(cwd, wt_dir).split(os.sep)[0]
            if name in existing:
                continue
            by_worktree.setdefault(name, []).extend(pids)
        return [
            Problem(
                "orphans",
                "worktree %s no longer exists but %d live process(es) remain: %s" % (
                    os.path.join(wt_dir, name), len(pids),
                    ", ".join(str(p) for p in sorted(pids))),
            )
            for name, pids in sorted(by_worktree.items())
        ]
