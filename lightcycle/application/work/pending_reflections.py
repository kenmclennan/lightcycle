def item_reflection_count(store, item):
    count = sum(1 for a in store.item_artifacts(item.id) if a.type == "reflection")
    for step in store.children(item.id):
        if step.type == "step":
            count += sum(1 for a in store.item_artifacts(step.id) if a.type == "reflection")
    return count


def pending_reflection_count(store):
    return sum(item_reflection_count(store, item) for item in store.closed_unretroed_items())
