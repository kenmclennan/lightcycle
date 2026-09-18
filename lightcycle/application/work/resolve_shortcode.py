from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.domain.work import ProjectIdentity
from lightcycle.ports.store import ProjectResolutionError


@dataclass(frozen=True)
class ResolvedShortcode:
    value: str
    defaulted: bool
    project: Optional[str] = None


def resolve_shortcode(store, config, project, repo=None):
    if project:
        try:
            matched = ProjectRegistry(store).find(project)
        except ProjectResolutionError as e:
            raise UseCaseError(str(e))
        if not matched.shortcode:
            raise UseCaseError(
                "project '%s' is registered but has no shortcode - run `lc project add %s "
                "--shortcode <PREFIX>` to set one" % (matched.identity, matched.identity)
            )
        return ResolvedShortcode(matched.shortcode, False)
    if repo:
        try:
            matched = ProjectRegistry(store).find(repo)
        except ProjectResolutionError:
            matched = None
        if matched and matched.shortcode:
            return ResolvedShortcode(matched.shortcode, False, ProjectIdentity.short_name(matched.identity))
    return ResolvedShortcode(config.shortcode(), True)
