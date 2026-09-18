class ListGoalsUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self):
        return self._store.list_goals()
