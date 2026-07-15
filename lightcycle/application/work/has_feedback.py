def has_feedback(store, item):
    if any(a.type == "reflection" for a in store.item_artifacts(item.id)):
        return True
    return any(
        a.type == "reflection"
        for step in store.children(item.id) if step.type == "step"
        for a in store.item_artifacts(step.id)
    )
