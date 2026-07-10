from dataclasses import dataclass, field
from typing import List

from lightcycle.domain.work import Item, State


@dataclass(frozen=True)
class RetroCadenceResponse:
    fired: List[str] = field(default_factory=list)


class RetroCadenceUseCase:

    def __init__(self, store, flow_service, config):
        self._store = store
        self._flow_service = flow_service
        self._config = config

    def execute(self, now: float) -> RetroCadenceResponse:
        interval = self._config.retro_interval_items()
        flow = self._flow_service.load_flow()
        cadence_steps = flow.retro_cadence_steps()
        if not cadence_steps:
            return RetroCadenceResponse()

        by_project = {}
        for item in self._store.closed_unretroed_items():
            project = self._project_of(item)
            if project is None:
                continue
            by_project.setdefault(project, []).append(item)

        fired = []
        for step, role in cadence_steps:
            open_projects = self._open_audit_projects(step)
            for project, items in by_project.items():
                if project in open_projects or len(items) < interval:
                    continue
                tid = self._store.create_step(
                    "%s: %s trend audit" % (step, project),
                    step=step, role=role, project=project)
                fired.append(tid)

        return RetroCadenceResponse(fired=fired)

    def _project_of(self, item):
        return Item(item.id, tuple(self._store.item_artifacts(item.id))).artifact_of("repo")

    def _open_audit_projects(self, step):
        return {
            s.project for s in self._store.steps_at_step(step)
            if s.state != State.DONE and s.project
        }
