class ListGoalsUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, include_archived=False):
        goals = self._store.list_goals()
        if include_archived:
            return goals
        return [g for g in goals if g.status != "archived"]
