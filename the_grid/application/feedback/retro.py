"""Retro: gather an epic's child feedback + objective signals into a digest."""
import json

from the_grid.core import retro as cretro
from the_grid.core.tasks import task_from_bead


class Retro:

    def __init__(self, store):
        self._store = store

    def _reflections_of(self, bead_id):
        out = []
        for art in self._store.story_artifacts(bead_id):
            if art.get("type") == "reflection":
                try:
                    out.append(json.loads(art["value"]))
                except (ValueError, KeyError):
                    pass
        return out

    def _story_signals(self, story_id):
        children = self._store.children(story_id)
        tasks = [task_from_bead(b) for b in children]
        task_histories = {t.id: self._store.history(t.id)
                          for t in tasks if t.step == "build"}
        return cretro.derive_signals(tasks, task_histories)

    def execute(self, epic):
        children = self._store.children(epic)
        stories = [task_from_bead(b) for b in children if b.get("issue_type") == "story"]
        all_reflections = []
        story_rows = []
        for story in stories:
            nrefs = 0
            for task in self._store.children(story.id):  # feedback sits on the task that gave it
                refs = self._reflections_of(task["id"])
                all_reflections.extend(refs)
                nrefs += len(refs)
            story_rows.append({"story": story, "signals": self._story_signals(story.id),
                               "nrefs": nrefs})
        # non-story epic children (e.g. a plan task) reflect on themselves
        for child in children:
            if child.get("issue_type") != "story":
                all_reflections.extend(self._reflections_of(child["id"]))
        return {"epic": epic, "n": len(all_reflections),
                "feedback": cretro.gather_feedback(all_reflections),
                "story_signals": story_rows}
