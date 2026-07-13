from dataclasses import dataclass, field
from typing import List

from lightcycle.application.work.project_of import project_of
from lightcycle.domain.work import State


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
            project = project_of(self._store, item)
            if project is None:
                continue
            by_project.setdefault(project, []).append(item)

        fired = []
        for step, role in cadence_steps:
            open_projects = self._open_audit_projects(step)
            for project, items in by_project.items():
                if project in open_projects or len(items) < interval:
                    continue
                item_id = self._store.create_item(project, project=project)
                self._store.add_artifact(item_id, "repo", project)
                self._store.label_add(item_id, "retro-origin")
                tid = self._store.create_step(
                    "%s: %s" % (step, project),
                    step=step, role=role, parent=item_id, project=project)
                fired.append(tid)

        return RetroCadenceResponse(fired=fired)

    def _open_audit_projects(self, step):
        return {
            s.project for s in self._store.steps_at_step(step)
            if s.state != State.DONE and s.project
        }
