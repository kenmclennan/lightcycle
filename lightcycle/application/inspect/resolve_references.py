class ResolveReferencesUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, ids):
        return {i: self._title(i) for i in dict.fromkeys(ids)}

    def _title(self, ref_id):
        try:
            title = self._store.get_node(ref_id).title
        except KeyError:
            title = None
        return title or None
