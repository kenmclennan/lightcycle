"""CloseEpic: close an epic only when all its child stories are already closed."""
import json
from dataclasses import dataclass

from the_grid.application.errors import UseCaseError
from the_grid.application.feedback.retro import RetroInput, RetroResponse, RetroUseCase


@dataclass(frozen=True)
class CloseEpicInput:
    epic: str
    reason: str


@dataclass(frozen=True)
class CloseEpicResponse:
    retro: RetroResponse


class CloseEpicUseCase:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: CloseEpicInput) -> CloseEpicResponse:
        children = self._store.children(input.epic)
        open_stories = [c for c in children if c.type == "story" and c.status != "done"]
        if open_stories:
            ids = ", ".join(c.id for c in open_stories)
            raise UseCaseError(
                "epic %s has open stories: %s - close or abandon them first"
                % (input.epic, ids)
            )
        self._store.close(input.epic, input.reason)
        retro = RetroUseCase(self._store, self._flow).execute(RetroInput(subject=input.epic))
        digest = json.dumps({
            "feedback": [{"task": f.task, "text": f.text} for f in retro.feedback],
            "story_signals": [
                {"story": row.story.id, "signals": row.signals, "reflections": row.reflections}
                for row in retro.story_signals
            ],
        })
        self._store.add_artifact(input.epic, "retro", digest)
        return CloseEpicResponse(retro=retro)
