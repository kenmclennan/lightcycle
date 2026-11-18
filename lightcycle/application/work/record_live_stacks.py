from lightcycle.application.pool.stack_reads import read_stack, record_final_stack


class RecordLiveStacksUseCase:
    def __init__(self, store, github):
        self._store = store
        self._github = github

    def execute(self, item) -> None:
        for run in self._store.open_runs_of(item):
            if not run.stack:
                continue
            stack = read_stack(self._github, run.stack)
            if stack.layers:
                record_final_stack(self._store, run, stack)
