"""FileStory: create a story (for one repo) from a spec + its first task."""
import os
from dataclasses import dataclass
from typing import List, Optional

from the_grid.application.errors import UseCaseError
from the_grid.domain.contracts import FILE_PROVIDES, StepContract


@dataclass(frozen=True)
class FileStoryInput:
    spec: str
    step: str
    epic: Optional[str] = None
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
        pr = self._config.projects_root()
        return [name for name in self._fs.list_dir(pr)
                if self._git.is_git_repo(os.path.join(pr, name))]

    def execute(self, input: FileStoryInput) -> FileStoryResponse:
        flow = self._flow.load_flow()
        role = flow.owner_of(input.step)
        if not role:
            raise UseCaseError("unknown step '%s'; owned steps: %s"
                               % (input.step, ", ".join(flow.steps()) or "(none)"))
        unmet = StepContract.from_meta(self._flow.meta_for_step(input.step)).missing_inputs(FILE_PROVIDES)
        if unmet:
            raise UseCaseError(
                "step '%s' requires %s; a filed story only carries a spec. "
                "File at an entry step." % (input.step, ", ".join(sorted(unmet))))
        if input.repo and not self._git.is_git_repo(self._repo_path(input.repo)):
            avail = ", ".join(self._available_repos()) or "(none)"
            raise UseCaseError("unknown repo '%s'; available repos: %s" % (input.repo, avail))
        base = os.path.splitext(os.path.basename(input.spec))[0]
        story = self._store.create_story(base, epic=input.epic,
                                         project=input.project, goal=input.goal)
        self._store.add_artifact(story, "spec", input.spec)
        if input.repo:
            self._store.add_artifact(story, "repo", input.repo)
        task = self._store.create_task("%s: %s" % (input.step, base),
                                       step=input.step, role=role, parent=story)
        for blocker in (input.blocked_by or []):
            self._store.dep_add(task, blocker)
        return FileStoryResponse(story=story)
