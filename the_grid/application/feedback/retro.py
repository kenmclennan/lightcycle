"""Retro: gather an epic's child feedback + its declared signals into a digest."""
import json
from dataclasses import dataclass
from typing import Dict, List

from the_grid.domain import feedback as cfeedback
from the_grid.domain.work import Task


@dataclass(frozen=True)
class RetroInput:
    epic: str


@dataclass(frozen=True)
class FeedbackItem:
    task: str
    text: str


@dataclass(frozen=True)
class StorySignals:
    story: Task
    signals: Dict[str, int]
    reflections: int


@dataclass(frozen=True)
class RetroResponse:
    epic: str
    reflection_count: int
    feedback: List[FeedbackItem]
    story_signals: List[StorySignals]


class RetroUseCase:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def _reflections_of(self, bead_id):
        out = []
        for art in self._store.story_artifacts(bead_id):
            if art.type == "reflection":
                try:
                    out.append(cfeedback.Reflection.from_dict(json.loads(art.value)))
                except (ValueError, KeyError):
                    pass
        return out

    def execute(self, input: RetroInput) -> RetroResponse:
        signals = cfeedback.Signals.from_metas(self._flow.role_metas())
        children = self._store.children(input.epic)
        stories = [c for c in children if c.type == "story"]
        all_reflections = []
        rows = []
        for story in stories:
            story_tasks = self._store.children(story.id)
            nrefs = 0
            for task in story_tasks:  # feedback sits on the task that gave it
                refs = self._reflections_of(task.id)
                all_reflections.extend(refs)
                nrefs += len(refs)
            rows.append(StorySignals(story=story, signals=signals.tally(story_tasks),
                                     reflections=nrefs))
        # non-story epic children (e.g. a plan task) reflect on themselves
        for child in children:
            if child.type != "story":
                all_reflections.extend(self._reflections_of(child.id))
        feedback = [FeedbackItem(task=f["task"], text=f["feedback"])
                    for f in cfeedback.Retro(all_reflections).feedback()]
        return RetroResponse(epic=input.epic, reflection_count=len(all_reflections),
                             feedback=feedback, story_signals=rows)
