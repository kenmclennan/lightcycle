from lightcycle.application.work.retroed_passes import retroed_pass_ids
from lightcycle.domain.feedback import reflections_of


def has_feedback(store, item):
    steps = [(s.pass_id, store.item_artifacts(s.id))
             for s in store.children(item.id) if s.type == "step"]
    return bool(reflections_of(store.item_artifacts(item.id), steps, retroed_pass_ids(store, item.id)))
