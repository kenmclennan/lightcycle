import os
from dataclasses import dataclass
from typing import List

from lightcycle.application.errors import UseCaseError

ORPHAN_RECHECK_SECONDS = 2


@dataclass(frozen=True)
class OrphanedWorktree:
    path: str
    exists: bool
    pids: List[int]


class OrphanedWorktrees:
    def __init__(self, store, fs, machine, worktrees, sleep):
        self._store = store
        self._fs = fs
        self._machine = machine
        self._worktrees = worktrees
        self._sleep = sleep

    def scan(self):
        expected = self._expected_worktree_paths()
        candidates = {}
        for project in self._store.list_projects():
            if not project.local_path:
                continue
            wt_dir = self._fs.worktrees_dir(project.local_path)
            by_worktree = self._pids_by_worktree(wt_dir)
            existing = set(self._fs.list_dir(wt_dir))
            names = self._candidates(wt_dir, existing, expected, by_worktree)
            if names:
                candidates[wt_dir] = names
        if not candidates:
            return []
        self._sleep(ORPHAN_RECHECK_SECONDS)
        expected = self._expected_worktree_paths()
        found = []
        for wt_dir, names in candidates.items():
            by_worktree = self._pids_by_worktree(wt_dir)
            existing = set(self._fs.list_dir(wt_dir))
            found += self._existing(wt_dir, existing, expected, by_worktree, names)
            found += self._deleted(wt_dir, existing, expected, by_worktree, names)
        return found

    def pids_still_under(self, worktree):
        wt_dir, name = os.path.split(worktree)
        return sorted(self._pids_by_worktree(wt_dir).get(name, ()))

    def _expected_worktree_paths(self):
        expected = set()
        for step in self._store.claimed_steps():
            try:
                expected.add(self._worktrees.worktree_path(step))
            except UseCaseError:
                continue
        return expected

    def _candidates(self, wt_dir, existing, expected, by_worktree):
        names = set()
        for name, pids in by_worktree.items():
            path = os.path.join(wt_dir, name)
            if not pids or path in expected:
                continue
            if name in existing or not self._fs.exists(path):
                names.add(name)
        return names

    def _existing(self, wt_dir, existing, expected, by_worktree, names):
        found = []
        for name in sorted(existing & names):
            path = os.path.join(wt_dir, name)
            pids = sorted(by_worktree.get(name, ()))
            if path in expected or not pids:
                continue
            found.append(OrphanedWorktree(path, True, pids))
        return found

    def _pids_by_worktree(self, wt_dir):
        by_worktree = {}
        for cwd, pids in self._machine.cwd_pids_under(wt_dir).items():
            name = os.path.relpath(cwd, wt_dir).split(os.sep)[0]
            by_worktree.setdefault(name, set()).update(pids)
        return by_worktree

    def _deleted(self, wt_dir, existing, expected, by_worktree, names):
        found = []
        for name, pids in sorted(by_worktree.items()):
            if name not in names:
                continue
            path = os.path.join(wt_dir, name)
            if name in existing or path in expected or self._fs.exists(path):
                continue
            found.append(OrphanedWorktree(path, False, sorted(pids)))
        return found
