import os
from dataclasses import dataclass
from typing import List, Optional

from the_grid.application.errors import UseCaseError
from the_grid.domain.contracts import FILE_PROVIDES, StepContract
from the_grid.domain.work.status import Status

_NESTED_REPO_MAX_DEPTH = 2


@dataclass(frozen=True)
class FileStoryInput:
    spec: str
    step: str
    epic: str
    project: Optional[str] = None
    goal: Optional[str] = None
    repo: Optional[str] = None
    blocked_by: Optional[List[str]] = None


@dataclass(frozen=True)
class FileStoryResponse:
    story: str


class FileStoryUseCase:
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

    def _require_open_epic(self, epic_id):
        if not epic_id:
            raise UseCaseError(
                "tg file requires --epic <id>; open one with `tg epic \"<objective>\"`"
            )
        try:
            epic = self._store.get_task(epic_id)
        except KeyError:
            raise UseCaseError("unknown epic '%s'" % epic_id)
        if epic.type != "epic":
            raise UseCaseError("'%s' is not an epic (type=%s)" % (epic_id, epic.type))
        if epic.status == Status.DONE:
            raise UseCaseError("epic '%s' is already closed" % epic_id)

    def execute(self, input: FileStoryInput) -> FileStoryResponse:
        flow = self._flow.load_flow()
        role = flow.owner_of(input.step)
        if not role:
            raise UseCaseError(
                "unknown step '%s'; owned steps: %s"
                % (input.step, ", ".join(flow.steps()) or "(none)")
            )
        unmet = StepContract.from_meta(self._flow.meta_for_step(input.step)).missing_inputs(
            FILE_PROVIDES
        )
        if unmet:
            raise UseCaseError(
                "step '%s' requires %s; a filed story only carries a spec. "
                "File at an entry step." % (input.step, ", ".join(sorted(unmet)))
            )
        self._require_open_epic(input.epic)
        if input.repo and not self._git.is_git_repo(self._repo_path(input.repo)):
            avail = ", ".join(self._available_repos()) or "(none)"
            raise UseCaseError("unknown repo '%s'; available repos: %s" % (input.repo, avail))
        base = os.path.splitext(os.path.basename(input.spec))[0]
        story = self._store.create_story(
            base, epic=input.epic, project=input.project, goal=input.goal
        )
        task = None
        try:
            self._store.add_artifact(story, "spec", input.spec)
            if input.repo:
                self._store.add_artifact(story, "repo", input.repo)
            task = self._store.create_task(
                "%s: %s" % (input.step, base), step=input.step, role=role, parent=story
            )
            for blocker in input.blocked_by or []:
                self._store.dep_add(task, blocker)
        except Exception:
            if task:
                self._store.delete(task)
            self._store.delete(story)
            raise
        return FileStoryResponse(story=story)
