from lightcycle.domain.work.refused_route import REFUSED_ROUTE


class RefusedRoute:
    def __init__(self, store):
        self._store = store

    def outcome_of(self, step_id):
        found = None
        for artifact in self._store.item_artifacts(step_id):
            if artifact.type == REFUSED_ROUTE:
                found = artifact.value
        return found if found and found.strip() else None

    def record(self, step_id, outcome):
        self._store.replace_artifact(step_id, REFUSED_ROUTE, outcome, internal=True)

    def clear(self, step_id):
        self._store.remove_artifact(step_id, REFUSED_ROUTE)
