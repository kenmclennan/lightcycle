def item_reflection_count(store, item):
    count = sum(1 for a in store.item_artifacts(item.id) if a.type == "reflection")
    retroed_passes = {p.id for p in store.passes_of(item.id) if "retroed" in store.labels_of(p.id)}
    for step in store.children(item.id):
        if step.type != "step" or step.pass_id in retroed_passes:
            continue
        count += sum(1 for a in store.item_artifacts(step.id) if a.type == "reflection")
    return count


def pass_reflection_count(store, pass_record):
    steps = [s for s in store.children(pass_record.item) if s.pass_id == pass_record.id]
    return sum(
        1 for s in steps for a in store.item_artifacts(s.id) if a.type == "reflection"
    )


def pending_reflection_count(store):
    from_items = sum(item_reflection_count(store, item) for item in store.closed_unretroed_items())
    from_passes = sum(pass_reflection_count(store, p) for p in store.closed_unretroed_passes())
    return from_items + from_passes
