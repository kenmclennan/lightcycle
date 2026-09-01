from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.ports.store import ProjectResolutionError


@dataclass(frozen=True)
class ResolvedShortcode:
    value: str
    defaulted: bool


def resolve_shortcode(store, config, project):
    if not project:
        return ResolvedShortcode(config.shortcode(), True)
    try:
        matched = store.find_project(project)
    except ProjectResolutionError as e:
        raise UseCaseError(str(e))
    if not matched.shortcode:
        raise UseCaseError(
            "project '%s' is registered but has no shortcode - run `lc project add %s "
            "--shortcode <PREFIX>` to set one" % (matched.identity, matched.identity)
        )
    return ResolvedShortcode(matched.shortcode, False)
