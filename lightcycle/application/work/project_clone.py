import os

from lightcycle.application.errors import UseCaseError
from lightcycle.ports.store import ProjectResolutionError


def ensure_project_cloned(store, git, config, ref):
    if not ref or os.path.isabs(ref):
        return
    try:
        project = store.find_project(ref)
    except ProjectResolutionError as e:
        raise UseCaseError(str(e))
    if project.local_path:
        if not os.path.isdir(project.local_path):
            raise UseCaseError(
                "project '%s' is registered at '%s' but that directory is missing - re-run "
                "`lc project add %s --path <dir>` to point at a real checkout"
                % (project.identity, project.local_path, project.identity)
            )
        return
    dest = os.path.join(config.projects_root(), *project.identity.split("/"))
    if os.path.isdir(dest):
        if not git.is_git_repo(dest):
            raise UseCaseError(
                "clone destination '%s' for '%s' already exists and is not a git repo - "
                "remove or repoint it by hand" % (dest, project.identity)
            )
    elif not git.clone_identity(project.identity, dest):
        raise UseCaseError(
            "failed to clone '%s' into '%s' via `gh repo clone` - check `gh auth status` and "
            "access to the repo" % (project.identity, dest)
        )
    store.add_project(project.identity, local_path=dest)
