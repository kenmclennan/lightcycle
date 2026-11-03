from lightcycle.application.services.guidance_library import GuidanceLibrary
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from lightcycle.domain.guidance.guidance import (
    GuidanceSelection, deliver, render_section,
)
from lightcycle.domain.workflows.identity import parse_pin
from lightcycle.ports.store import ProjectNotRegisteredError, ProjectResolutionError


class SelectGuidanceUseCase:
    def __init__(self, store, fs, git, config):
        self._store = store
        self._fs = fs
        self._git = git
        self._config = config

    def _project_scope(self, item_id):
        item = self._store.get_item(item_id)
        if not item.repo:
            return (), None, item.project
        try:
            found = ProjectRegistry(self._store).find(item.repo)
        except (ProjectNotRegisteredError, ProjectResolutionError):
            return (), item.repo, item.project
        return found.facets, found.identity, item.project

    def execute(self, item_id, stage, pin, step_id):
        project = self._store.get_project(GUIDANCE_WORKSPACE)
        if project is None or not project.local_path:
            return GuidanceSelection(notes=("no guidance repo is registered",))
        if not self._fs.exists(project.local_path):
            return GuidanceSelection(
                notes=("guidance repo is missing at %s" % project.local_path,))
        entries, problems = GuidanceLibrary(self._git).load(project.local_path)
        notes = tuple("%s: %s" % (name, reason) for name, reason in problems)
        facets, repo, label = self._project_scope(item_id)
        parsed = parse_pin(pin)
        origin = parsed[0] if parsed else None
        _, delivered, skipped = deliver(
            entries, facets, repo, label, stage, origin, self._config.guidance_budget_bytes())
        return GuidanceSelection(
            section=render_section(delivered, step_id) if delivered else "",
            delivered=tuple(e.id for e in delivered),
            skipped=tuple(e.id for e in skipped),
            notes=notes,
        )
