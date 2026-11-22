import errno
import os
from dataclasses import dataclass
from typing import Tuple

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.work.project_paths import is_under, rewrite_value, translate
from lightcycle.ports.git import GitReadError

PATH_CONFIG_KEYS = ("projects", "backups-dir", "guidance-path", "specs-path")


@dataclass(frozen=True)
class RelocateResult:
    lines: Tuple[str, ...]
    config_rewritten: bool = False


@dataclass
class _Plan:
    project: object
    old: str
    new: str
    snapshot: tuple = ()
    translated: tuple = ()


class RelocateProjectUseCase:
    def __init__(self, store, git, fs, config, config_edit, worktrees):
        self._store = store
        self._git = git
        self._fs = fs
        self._config = config
        self._config_edit = config_edit
        self._worktrees = worktrees

    def move(self, identity, new_dir):
        project = self._registered(identity)
        if not project.local_path:
            raise UseCaseError(
                "project %s has no local checkout - run `lc project set %s --path <dir>`"
                % (identity, identity)
            )
        old = os.path.abspath(project.local_path)
        new = _absolute(new_dir)
        return self._relocate(old, new, [project], single=True)

    def move_prefix(self, old_dir, new_dir):
        old = _absolute(old_dir)
        new = _absolute(new_dir)
        projects = [
            p for p in self._store.list_projects()
            if p.local_path and is_under(p.local_path, old)
        ]
        if not projects:
            raise UseCaseError("no registered project is under %s" % old)
        return self._relocate(old, new, projects, single=False)

    def set_path(self, identity, new_dir):
        project = self._registered(identity)
        new = _absolute(new_dir)
        if not project.local_path:
            return self._set_unchecked_out(project, new)
        old = os.path.abspath(project.local_path)
        if self._fs.exists(old):
            raise UseCaseError(
                "%s still exists; two live trees cannot both be the checkout - "
                "run `lc project mv %s %s` to move it" % (old, identity, new)
            )
        if not self._fs.exists(new):
            raise UseCaseError("%s does not exist" % new)
        if not self._git.is_repo_root(new):
            raise UseCaseError("%s is not a git repo root" % new)
        remote = self._remote(new)
        if project.remote and remote != project.remote:
            raise UseCaseError(
                "%s is a checkout of %s, not %s" % (new, remote, project.remote)
            )
        return self._relocate(old, new, [project], single=True)

    def _registered(self, identity):
        project = self._store.get_project(identity)
        if project is None:
            registered = [p.identity for p in self._store.list_projects()]
            raise UseCaseError(
                "project '%s' is not registered%s"
                % (identity, " - registered: %s" % ", ".join(registered) if registered else "")
            )
        return project

    def _remote(self, root):
        try:
            return self._git.remote_url(root)
        except GitReadError:
            return None

    def _set_unchecked_out(self, project, new):
        if not self._fs.exists(new) or not self._git.is_repo_root(new):
            raise UseCaseError("%s is not a git repo root" % new)
        self._store.add_project(project.identity, local_path=new, remote=self._remote(new))
        return RelocateResult(("%s -> %s" % (project.identity, new),))

    def _relocate(self, old_root, new_root, projects, single):
        resumed = not self._fs.exists(old_root) and self._fs.exists(new_root)
        self._refuse_active(projects)
        self._check_target(old_root, new_root, projects, single, resumed)
        plans = [
            _Plan(p, os.path.abspath(p.local_path), translate(p.local_path, old_root, new_root))
            for p in projects
        ]
        self._snapshot(plans, resumed)
        renamed = False
        if not resumed:
            self._rename(old_root, new_root)
            renamed = True
        lines = []
        try:
            self._repair(plans, old_root, new_root, lines)
        except UseCaseError as e:
            if renamed:
                self._roll_back(plans, old_root, new_root, str(e))
            raise
        for plan in plans:
            self._store.add_project(plan.project.identity, local_path=plan.new)
            lines.append("moved %s -> %s" % (plan.project.identity, plan.new))
        rewritten, failed = self._rewrite_config(old_root, new_root)
        for key in rewritten:
            lines.append("rewrote config %s" % key)
        for key, value in failed:
            lines.append("could not rewrite %s - run: lc config set %s %s" % (key, key, value))
        return RelocateResult(tuple(lines), bool(rewritten))

    def _refuse_active(self, projects):
        paths = {os.path.realpath(p.local_path): p for p in projects if p.local_path}
        for step in self._store.claimed_steps():
            try:
                repo = self._worktrees.target_repo(step)
            except UseCaseError:
                continue
            project = paths.get(os.path.realpath(repo))
            if project is not None:
                raise UseCaseError(
                    "cannot move %s: step %s is running in it" % (project.identity, step.id)
                )

    def _check_target(self, old_root, new_root, projects, single, resumed):
        if is_under(self._config.data_root(), old_root):
            raise UseCaseError(
                "the lightcycle home %s is inside %s; the store and config would move with it"
                % (self._config.data_root(), old_root)
            )
        if resumed:
            return
        if not self._fs.exists(old_root):
            raise UseCaseError(
                "%s does not exist - if you moved it by hand, run `lc project set <identity> "
                "--path %s`" % (old_root, new_root)
            )
        if single and not self._git.is_repo_root(old_root):
            raise UseCaseError("%s is not a git repo root" % old_root)
        if self._fs.exists(new_root):
            raise UseCaseError("%s already exists" % new_root)
        if not self._fs.exists(os.path.dirname(new_root)):
            raise UseCaseError("the parent of %s does not exist" % new_root)
        if is_under(new_root, old_root):
            raise UseCaseError("%s is inside %s" % (new_root, old_root))
        moving = {p.identity for p in projects}
        for other in self._store.list_projects():
            if other.identity not in moving and other.local_path and (
                is_under(other.local_path, new_root)
            ):
                raise UseCaseError(
                    "project %s is registered at %s, under %s"
                    % (other.identity, other.local_path, new_root)
                )

    def _snapshot(self, plans, resumed):
        for plan in plans:
            root = plan.new if resumed else plan.old
            try:
                entries = self._git.list_worktrees(root)
            except GitReadError as e:
                raise UseCaseError("cannot list worktrees of %s: %s" % (plan.project.identity, e))
            plan.snapshot = tuple(e.path for e in entries)

    def _rename(self, old_root, new_root):
        try:
            self._fs.rename_dir(old_root, new_root)
        except OSError as e:
            if e.errno == errno.EXDEV:
                raise UseCaseError(
                    "%s is on a different filesystem; move it by hand then run "
                    "lc project set" % new_root
                )
            raise UseCaseError("could not move %s to %s: %s" % (old_root, new_root, e))

    def _repair(self, plans, old_root, new_root, lines):
        for plan in plans:
            plan.translated = tuple(translate(p, old_root, new_root) for p in plan.snapshot)
            present = [p for p in plan.translated if self._fs.exists(p)]
            for path in plan.translated:
                if path not in present:
                    lines.append(
                        "worktree %s is missing and was left for git worktree prune" % path
                    )
            outcome = self._git.repair_worktrees(plan.new, present)
            if not outcome.ok:
                raise UseCaseError(outcome.detail or "git worktree repair failed")
            try:
                listed = self._git.list_worktrees(plan.new)
            except GitReadError as e:
                raise UseCaseError("cannot list worktrees of %s: %s" % (plan.new, e))
            wanted = set(present)
            stuck = [e.path for e in listed if e.prunable and e.path in wanted]
            if stuck:
                raise UseCaseError("worktree %s is still prunable after repair" % stuck[0])
            lines.append("repaired %d worktree(s) of %s" % (len(present), plan.project.identity))

    def _roll_back(self, plans, old_root, new_root, reason):
        try:
            self._fs.rename_dir(new_root, old_root)
        except OSError as e:
            raise UseCaseError(
                "%s; and moving %s back to %s failed (%s) - move it back by hand and run "
                "`git -C <repo> worktree repair <worktree paths>`; the registry still names %s"
                % (reason, new_root, old_root, e, old_root)
            )
        for plan in plans:
            self._git.repair_worktrees(plan.old, [p for p in plan.snapshot if self._fs.exists(p)])

    def _rewrite_config(self, old_root, new_root):
        home = self._config.home_dir()
        values = self._config.load_config()
        candidates = [(k, values.get(k)) for k in PATH_CONFIG_KEYS]
        for key, value in values.items():
            if key.startswith("callout-") and isinstance(value, dict):
                candidates.append(("%s.command" % key, value.get("command")))
        rewritten, failed = [], []
        for key, value in candidates:
            if not isinstance(value, str):
                continue
            updated = rewrite_value(value, old_root, new_root, home)
            if updated is None:
                continue
            try:
                self._config_edit.set(key, [updated])
                rewritten.append(key)
            except UseCaseError:
                failed.append((key, updated))
        return rewritten, failed


def _absolute(path):
    return os.path.abspath(os.path.expanduser(path))
