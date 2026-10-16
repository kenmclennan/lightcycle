from lightcycle.domain.work.behind_marker import BEHIND_NOT_UPDATED


def behind_reason(store, step_id):
    found = None
    for artifact in store.item_artifacts(step_id):
        if artifact.type == BEHIND_NOT_UPDATED:
            found = artifact.value
    return found if found and found.strip() else None
