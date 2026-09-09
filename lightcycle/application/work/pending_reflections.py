from lightcycle.application.work.retroed_passes import retroed_pass_ids
from lightcycle.domain.feedback import reflections_of


def item_reflection_count(store, item):
    steps = [(s.pass_id, store.item_artifacts(s.id))
             for s in store.children(item.id) if s.type == "step"]
    return len(reflections_of(store.item_artifacts(item.id), steps, retroed_pass_ids(store, item.id)))


def pass_reflection_count(store, pass_record):
    steps = [s for s in store.children(pass_record.item) if s.pass_id == pass_record.id]
    step_pairs = [(s.pass_id, store.item_artifacts(s.id)) for s in steps]
    return len(reflections_of([], step_pairs, set()))


def pending_reflection_count(store):
    from_items = sum(item_reflection_count(store, item) for item in store.closed_unretroed_items())
    from_passes = sum(pass_reflection_count(store, p) for p in store.closed_unretroed_passes())
    return from_items + from_passes
