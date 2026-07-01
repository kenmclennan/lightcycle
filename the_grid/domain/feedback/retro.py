"""Retro: an epic's retro digest - the freeform feedback its workers left (an aggregate)."""


class Retro:

    def __init__(self, reflections):
        self._reflections = reflections

    def feedback(self):
        """The freeform feedback texts (with their task ids) for reading or LLM
        analysis - no counting or categorising; the raw text is the signal."""
        return [{"task": r.task, "feedback": r.feedback}
                for r in self._reflections if (r.feedback or "").strip()]
