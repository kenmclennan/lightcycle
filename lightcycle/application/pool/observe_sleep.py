from lightcycle.domain.pool.sleep import SLEEP_RETENTION_SECONDS, detect_sleep


class ObserveSleepUseCase:
    def __init__(self, ledger):
        self._ledger = ledger

    def execute(self, wall_now, awake_now):
        state = self._ledger.load()
        sample = state.get("sample")
        sample = (float(sample[0]), float(sample[1])) if sample else None
        sleeps = [(float(a), float(b)) for a, b in state.get("sleeps", [])]
        found = detect_sleep(sample, wall_now, awake_now)
        if found is not None:
            sleeps.append(found)
        horizon = wall_now - SLEEP_RETENTION_SECONDS
        sleeps = [s for s in sleeps if s[1] >= horizon]
        self._ledger.save({"sample": [wall_now, awake_now], "sleeps": [list(s) for s in sleeps]})
        return tuple(sleeps)
