"""Retro: gather feedback + signals into a digest at story, epic, or window scope."""
import json
from dataclasses import dataclass
from typing import Dict, List, Optional

from the_grid.domain import feedback as cfeedback
from the_grid.domain.work import Task


@dataclass(frozen=True)
class RetroInput:
    subject: Optional[str] = None
    since: Optional[str] = None
    last: Optional[int] = None


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
    subject: str
    reflection_count: int
    feedback: List[FeedbackItem]
    story_signals: List[StorySignals]


class RetroUseCase:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def _reflections_of(self, task_id):
        out = []
        for art in self._store.story_artifacts(task_id):
            if art.type == "reflection":
                try:
                    out.append(cfeedback.Reflection.from_dict(json.loads(art.value)))
                except (ValueError, KeyError):
                    pass
        return out

    def _collect_story_row(self, story, signals):
        children = self._store.children(story.id)
        tasks = [c for c in children if c.type == "task"]
        refs = []
        for t in tasks:
            refs.extend(self._reflections_of(t.id))
        return StorySignals(story=story, signals=signals.tally(tasks), reflections=len(refs)), refs

    def _epic_scope(self, subject_id, signals):
        children = self._store.children(subject_id)
        stories = [c for c in children if c.type == "story"]
        all_refs = []
        rows = []
        for story in stories:
            row, refs = self._collect_story_row(story, signals)
            rows.append(row)
            all_refs.extend(refs)
        for child in children:
            if child.type != "story":
                all_refs.extend(self._reflections_of(child.id))
        return rows, all_refs

    def execute(self, input: RetroInput) -> RetroResponse:
        signals = cfeedback.Signals.from_metas(self._flow.role_metas())

        if input.subject is not None:
            children = self._store.children(input.subject)
            if any(c.type == "story" for c in children):
                rows, all_refs = self._epic_scope(input.subject, signals)
            else:
                subject = self._store.get_task(input.subject)
                row, refs = self._collect_story_row(subject, signals)
                rows = [row]
                all_refs = list(refs)
            label = input.subject

        elif input.since is not None:
            tasks = self._store.tasks_closed_since(input.since)
            story_groups = {}
            orphan_tasks = []
            for task in tasks:
                if task.parent:
                    story_groups.setdefault(task.parent, []).append(task)
                else:
                    orphan_tasks.append(task)
            all_refs = []
            rows = []
            for story_id, story_tasks in story_groups.items():
                refs = []
                for t in story_tasks:
                    refs.extend(self._reflections_of(t.id))
                all_refs.extend(refs)
                story = self._store.get_task(story_id)
                rows.append(StorySignals(story=story, signals=signals.tally(story_tasks),
                                         reflections=len(refs)))
            for task in orphan_tasks:
                all_refs.extend(self._reflections_of(task.id))
            label = "since:%s" % input.since

        else:
            epics = self._store.last_n_closed_epics(input.last)
            all_refs = []
            rows = []
            for epic in epics:
                epic_rows, epic_refs = self._epic_scope(epic.id, signals)
                rows.extend(epic_rows)
                all_refs.extend(epic_refs)
            label = "last:%d" % input.last

        feedback = [FeedbackItem(task=f["task"], text=f["feedback"])
                    for f in cfeedback.Retro(all_refs).feedback()]
        return RetroResponse(subject=label, reflection_count=len(all_refs),
                             feedback=feedback, story_signals=rows)
