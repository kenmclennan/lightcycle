"""Retro: gather an epic's child feedback + its declared signals into a digest."""
import json

from the_grid.domain import feedback as cfeedback


class Retro:

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

    def execute(self, epic):
        signals = cfeedback.Signals.from_metas(self._flow.role_metas())
        children = self._store.children(epic)
        stories = [c for c in children if c.type == "story"]
        all_reflections = []
        story_rows = []
        for story in stories:
            story_tasks = self._store.children(story.id)
            nrefs = 0
            for task in story_tasks:  # feedback sits on the task that gave it
                refs = self._reflections_of(task.id)
                all_reflections.extend(refs)
                nrefs += len(refs)
            story_rows.append({"story": story, "signals": signals.tally(story_tasks),
                               "nrefs": nrefs})
        # non-story epic children (e.g. a plan task) reflect on themselves
        for child in children:
            if child.type != "story":
                all_reflections.extend(self._reflections_of(child.id))
        return {"epic": epic, "n": len(all_reflections),
                "feedback": cfeedback.Retro(all_reflections).feedback(),
                "story_signals": story_rows}
