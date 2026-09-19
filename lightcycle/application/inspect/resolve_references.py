class ResolveReferencesUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, ids):
        return {i: self._title(i) for i in dict.fromkeys(ids)}

    def _title(self, ref_id):
        try:
            title = self._store.get_node(ref_id).title
        except KeyError:
            goal = self._store.get_goal(ref_id)
            title = goal.title if goal is not None else None
        return title or None
