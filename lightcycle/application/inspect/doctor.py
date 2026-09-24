import os
from dataclasses import dataclass
from typing import Dict, List

from lightcycle.application.errors import UseCaseError
from lightcycle.application.services.engine_fragments import with_engine_fragments
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
                expected.add(self._worktrees.worktree_path(step.item))
            except UseCaseError:
                continue
        return expected

    def _orphan_problems(self):
        expected = self._expected_worktree_paths()
        problems = []
        for project in self._store.list_projects():
            if not project.local_path:
                continue
            wt_dir = self._fs.worktrees_dir(project.local_path)
            for name in self._fs.list_dir(wt_dir):
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
        return problems
