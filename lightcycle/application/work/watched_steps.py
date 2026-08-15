def watched_step_ids(store):
    watched = set()
    for n in store.all_nodes():
        if n.type != "step":
            continue
        for a in store.item_artifacts(n.id):
            if a.type == "watched-step":
                watched.add(a.value)
    return watched
