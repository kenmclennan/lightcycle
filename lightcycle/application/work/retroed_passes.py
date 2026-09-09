def retroed_pass_ids(store, item_id):
    return {p.id for p in store.passes_of(item_id) if "retroed" in store.labels_of(p.id)}
