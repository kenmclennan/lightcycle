from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.domain.work import ProjectIdentity
from lightcycle.ports.store import ProjectResolutionError


def resolve_project_ref(store, ref):
    if ref is None:
        return None
    try:
        matched = ProjectRegistry(store).find(ref)
    except ProjectResolutionError as e:
        raise UseCaseError(str(e))
    return ProjectIdentity.short_name(matched.identity)
