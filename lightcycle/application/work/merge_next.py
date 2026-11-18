from lightcycle.domain.work.layer_ci_wait import MERGE_NEXT


def merge_next_of(store, step_id):
    found = None
    for artifact in store.item_artifacts(step_id):
        if artifact.type == MERGE_NEXT:
            found = artifact.value
    return found if found and found.strip() else None
