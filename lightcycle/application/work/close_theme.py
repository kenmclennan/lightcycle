import json
from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.application.feedback.retro import RetroInput, RetroResponse, RetroUseCase


@dataclass(frozen=True)
class CloseThemeInput:
    theme: str
    reason: str


@dataclass(frozen=True)
class CloseThemeResponse:
    retro: RetroResponse


class CloseThemeUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def _linked_backlog(self, theme):
        for artifact in self._store.item_artifacts(theme):
            if artifact.type == "backlog":
                return artifact.value
        return None

    def execute(self, input: CloseThemeInput) -> CloseThemeResponse:
        children = self._store.children(input.theme)
        open_stories = [c for c in children if c.type == "item" and c.status != "done"]
        if open_stories:
            ids = ", ".join(c.id for c in open_stories)
            raise UseCaseError(
                "theme %s has open items: %s - close or abandon them first" % (input.theme, ids)
            )
        self._store.close(input.theme, input.reason)
        backlog = self._linked_backlog(input.theme)
        if backlog:
            self._store.close(backlog, "resolved by theme close: %s" % input.theme)
        retro = RetroUseCase(self._store, self._flow).execute(RetroInput(subject=input.theme))
        digest = json.dumps(
            {
                "feedback": [{"step": f.step, "text": f.text} for f in retro.feedback],
                "item_signals": [
                    {
                        "item": row.item.id,
                        "signals": row.signals,
                        "reflections": row.reflections,
                        "durations": row.durations,
                        "duration": row.total_duration(),
                    }
                    for row in retro.item_signals
                ],
            }
        )
        self._store.add_artifact(input.theme, "retro", digest)
        theme = self._store.get_node(input.theme)
        flow = self._flow.load_flow(
            self._flow.workflow_for(theme), self._flow.project_for(theme)
        )
        for step, role in flow.theme_close_steps():
            tid = self._store.create_step(
                "%s: %s" % (step, theme.title),
                step=step,
                role=role,
            )
            self._store.update_metadata(tid, {"theme": input.theme})
        return CloseThemeResponse(retro=retro)
