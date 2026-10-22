class NoteReleaseHoldsUseCase:
    def __init__(self, store, holds, clock, note_seconds):
        self._store = store
        self._holds = holds
        self._clock = clock
        self._note_seconds = note_seconds
        self._since = {}
        self._noted = {}
        note_seconds()

    def execute(self):
        now = self._clock()
        held = self._holds.held_ids(self._store.ready_steps())
        for step_id in list(self._since):
            if step_id not in held:
                del self._since[step_id]
                self._noted.pop(step_id, None)
        bound = self._note_seconds()
        for step_id in sorted(held):
            since = self._since.setdefault(step_id, now)
            last = self._noted.get(step_id, since)
            if now - last < bound:
                continue
            self._noted[step_id] = now
            self._store.note_condition(
                step_id,
                "the item carries release-pending, so no step of it is claimed or started until "
                "a worktree release finishes; held for more than %d seconds "
                "(release-hold-note-seconds)" % bound,
            )
