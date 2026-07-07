class Retro:
    def __init__(self, reflections):
        self._reflections = reflections

    def feedback(self):
        return [
            {"step": r.step, "feedback": r.feedback}
            for r in self._reflections
            if (r.feedback or "").strip()
        ]
