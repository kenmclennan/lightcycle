import os
from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.contracts import FILE_PROVIDES, StepContract
from lightcycle.domain.work.status import Status

_NESTED_REPO_MAX_DEPTH = 2


@dataclass(frozen=True)
class FileItemInput:
    spec: str
    theme: str
    step: Optional[str] = None
    workflow: Optional[str] = None
    project: Optional[str] = None
    goal: Optional[str] = None
    repo: Optional[str] = None
    blocked_by: Optional[List[str]] = None


@dataclass(frozen=True)
class FileItemResponse:
    item: str


class FileItemUseCase:
    def __init__(self, store, flow, git, fs, config):
        self._store = store
        self._flow = flow
        self._git = git
        self._fs = fs
        self._config = config

    def _repo_path(self, repo):
        return os.path.join(self._config.projects_root(), repo)

    def _available_repos(self):
        found = []
        self._collect_repos(self._config.projects_root(), "", 1, found)
        return found

    def _collect_repos(self, abs_dir, rel_prefix, depth, found):
        for name in self._fs.list_dir(abs_dir):
            if name.startswith("."):
                continue
            child_abs = os.path.join(abs_dir, name)
            child_rel = "%s/%s" % (rel_prefix, name) if rel_prefix else name
            if self._git.is_git_repo(child_abs):
                found.append(child_rel)
            elif depth < _NESTED_REPO_MAX_DEPTH:
                self._collect_repos(child_abs, child_rel, depth + 1, found)

    def _require_open_theme(self, theme_id):
        if not theme_id:
            raise UseCaseError(
                "lc file requires --theme <id>; open one with `lc theme \"<objective>\"`"
            )
        try:
            theme = self._store.get_node(theme_id)
        except KeyError:
            raise UseCaseError("unknown theme '%s'" % theme_id)
        if theme.type != "theme":
            raise UseCaseError("'%s' is not a theme (type=%s)" % (theme_id, theme.type))
        if theme.status == Status.DONE:
            raise UseCaseError("theme '%s' is already closed" % theme_id)
        return theme

    def execute(self, input: FileItemInput) -> FileItemResponse:
        theme = self._require_open_theme(input.theme)
        workflow = input.workflow or self._flow.workflow_for(theme)
        project = input.project or self._flow.project_for(theme)
        step = input.step or self._flow.load_graph(workflow, project).entry
        flow = self._flow.load_flow(workflow, project)
        role = flow.owner_of(step)
        if not role:
            raise UseCaseError(
                "unknown step '%s' in workflow '%s'; owned steps: %s"
                % (step, workflow, ", ".join(flow.steps()) or "(none)")
            )
        unmet = StepContract.from_meta(
            self._flow.meta_for_step(step, workflow, project)
        ).missing_inputs(FILE_PROVIDES)
        if unmet:
            raise UseCaseError(
                "step '%s' requires %s; a filed item only carries a spec. "
                "File at an entry step." % (step, ", ".join(sorted(unmet)))
            )
        if input.repo and not self._git.is_git_repo(self._repo_path(input.repo)):
            avail = ", ".join(self._available_repos()) or "(none)"
            raise UseCaseError("unknown repo '%s'; available repos: %s" % (input.repo, avail))
        base = os.path.splitext(os.path.basename(input.spec))[0]
        item = self._store.create_item(
            base, theme=input.theme, project=input.project, goal=input.goal, workflow=input.workflow
        )
        step_id = None
        try:
            self._store.add_artifact(item, "spec", input.spec)
            if input.repo:
                self._store.add_artifact(item, "repo", input.repo)
            step_id = self._store.create_step(
                "%s: %s" % (step, base), step=step, role=role, parent=item
            )
            for blocker in input.blocked_by or []:
                self._store.dep_add(step_id, blocker)
        except Exception:
            if step_id:
                self._store.delete(step_id)
            self._store.delete(item)
            raise
        return FileItemResponse(item=item)
