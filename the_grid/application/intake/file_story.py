"""FileStory: create a story (for one repo) from a spec + its first task."""
import os

from the_grid.application.errors import UseCaseError
from the_grid.domain.contracts import FILE_PROVIDES, required_inputs


class FileStory:

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

    def execute(self, spec, step, *, epic=None, project=None, goal=None, repo=None, blocked_by=None):
        owner, _ = self._flow.load_flow()
        role = owner.get(step)
        if not role:
            raise UseCaseError("unknown step '%s'; owned steps: %s"
                               % (step, ", ".join(sorted(owner)) or "(none)"))
        unmet = required_inputs(self._flow.meta_for_step(step)) - FILE_PROVIDES
        if unmet:
            raise UseCaseError(
                "step '%s' requires %s; a filed story only carries a spec. "
                "File at an entry step." % (step, ", ".join(sorted(unmet))))
        if repo and not self._git.is_git_repo(self._repo_path(repo)):
            avail = ", ".join(self._available_repos()) or "(none)"
            raise UseCaseError("unknown repo '%s'; available repos: %s" % (repo, avail))
        base = os.path.splitext(os.path.basename(spec))[0]
        labels = []
        if project:
            labels.append("project:%s" % project)
        if goal:
            labels.append("goal:%s" % goal)
        story = self._store.create_story(base, epic=epic, labels=labels or None)
        self._store.add_artifact(story, "spec", spec)
        if repo:
            self._store.add_artifact(story, "repo", repo)
        task = self._store.create_task("%s: %s" % (step, base), step=step, role=role, parent=story)
        for blocker in (blocked_by or []):
            self._store.dep_add(task, blocker)
        return story
