import os
from dataclasses import dataclass
from typing import Dict, List

from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.guidance_library import GuidanceLibrary
from lightcycle.application.services.engine_fragments import with_engine_fragments
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE, LEGACY_KNOWLEDGE_WORKSPACE
from lightcycle.config import ConfigError
from lightcycle.domain.guidance.guidance import fill, matches_project, matches_step_key, order
from lightcycle.domain.health import Problem, fsck
from lightcycle.domain.work.state import State
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT, contract_compatible
from lightcycle.domain.workflows.identity import format_pin, parse_pin
from lightcycle.domain.workflows.source import parse_source_manifest


@dataclass(frozen=True)
class DoctorInput:
    pass


@dataclass(frozen=True)
class DoctorReport:
    problems: Dict[str, List[Problem]]

    def healthy(self) -> bool:
        return not any(self.problems.values())


class DoctorUseCase:
    def __init__(self, store, workflow_source, config, workflow_bundle, fs, machine, worktrees):
        self._store = store
        self._workflow_source = workflow_source
        self._config = config
        self._workflow_bundle = workflow_bundle
        self._fs = fs
        self._machine = machine
        self._worktrees = worktrees

    def execute(self, input: DoctorInput) -> DoctorReport:
        nodes = self._store.all_nodes_including_done()
        pins, contracts = self._bundle_problems(nodes)
        return DoctorReport(problems={
            "store": fsck(nodes),
            "pins": pins,
            "contract": contracts,
            "origin": self._origin_problems(),
            "config": self._config_problems(),
            "orphans": self._orphan_problems(),
            "facets": self._guidance_registration_problems() + self._facet_problems(),
            "guidance": self._guidance_problems(),
        })

    def _in_flight_pins(self, nodes):
        for n in nodes:
            if n.type != "item" or n.state == State.DONE:
                continue
            parsed = parse_pin(n.workflow)
            if parsed:
                yield n, parsed

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
                    changed = self._changed_step_roles(origin, sha, current)
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

    def _changed_step_roles(self, origin, old_sha, new_sha):
        old_root = self._workflow_source.pinned_bundle(origin, old_sha)
        new_root = self._workflow_source.pinned_bundle(origin, new_sha)
        roles = set(self._workflow_bundle.step_roles(old_root)) | set(self._workflow_bundle.step_roles(new_root))
        changed = set()
        old_roots = with_engine_fragments(old_root, self._config)
        new_roots = with_engine_fragments(new_root, self._config)
        for role in roles:
            old_step = self._workflow_bundle.parse_step(role, old_roots)
            new_step = self._workflow_bundle.parse_step(role, new_roots)
            old_body = old_step.body if old_step else None
            new_body = new_step.body if new_step else None
            if old_body != new_body:
                changed.add(role)
        return changed

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

    def _config_problems(self):
        missing = self._config.missing_config_keys()
        settings = self._config.resolved_settings()
        problems = [
            Problem("config", "required config key %r is not set" % k) for k in missing
        ]
        problems += [
            Problem("config", "required config key %r is set but blank" % s.key)
            for s in settings
            if s.state == "unset" and s.key not in missing
        ]
        problems += [
            Problem("config", "required config key %r is set but rejected: %s" % (s.key, s.error))
            for s in settings
            if s.state == "invalid"
        ]
        problems += [
            Problem("config", "config key %r is set but not read by this version" % k)
            for k in self._config.obsolete_config_keys()
        ]
        return problems

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
            for name in (f.rsplit("/", 1)[-1] for f in self._fs.list_files(root))
            if name.endswith(".md") and name != "index.md"
        }

    def _guidance_problems(self):
        repo = self._store.get_project(GUIDANCE_WORKSPACE)
        if repo is None or not repo.local_path or not self._fs.exists(repo.local_path):
            return []
        entries, unreadable = GuidanceLibrary(self._fs).load(repo.local_path)
        problems = [
            Problem(
                "guidance",
                "entry %s cannot be delivered: %s - fix its front matter in the guidance repo"
                % (name, reason),
            )
            for name, reason in unreadable
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
            if entry.status == "stable" and not entry.verified:
                problems.append(Problem(
                    "guidance",
                    "entry %s is stable but has no verified record - add `verified:` or "
                    "set its status to draft" % entry.id,
                ))
        problems += self._budget_problems([e for e in entries if e.is_candidate()])
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
