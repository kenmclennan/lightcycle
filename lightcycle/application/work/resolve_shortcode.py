from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.domain.work import ProjectIdentity
from lightcycle.ports.store import ProjectNotRegisteredError, ProjectResolutionError


@dataclass(frozen=True)
class ResolvedShortcode:
    value: str
    project: Optional[str] = None


def _registered_with_shortcode(store, name):
    try:
        matched = ProjectRegistry(store).find(name)
    except ProjectResolutionError as e:
        raise UseCaseError(str(e))
    if not matched.shortcode:
        raise UseCaseError(
            "project '%s' is registered but has no shortcode - run `lc project add %s "
            "--shortcode <PREFIX>` to set one" % (matched.identity, matched.identity)
        )
    return matched


def resolve_shortcode(store, project, repo=None):
    if project:
        return ResolvedShortcode(_registered_with_shortcode(store, project).shortcode)
    if repo:
        try:
            ProjectRegistry(store).find(repo)
        except ProjectNotRegisteredError:
            raise UseCaseError(
                "--repo '%s' is not a registered project - run `lc project add %s "
                "--shortcode <PREFIX>` to register it, or pass --project <registered project>"
                % (repo, repo)
            )
        except ProjectResolutionError as e:
            raise UseCaseError(str(e))
        matched = _registered_with_shortcode(store, repo)
        return ResolvedShortcode(matched.shortcode, ProjectIdentity.short_name(matched.identity))
    raise UseCaseError(
        "no project to mint under - pass --project <registered project>, or register the repo "
        "with `lc project add <repo> --shortcode <PREFIX>` and pass --repo <repo>"
    )
