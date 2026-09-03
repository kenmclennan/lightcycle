def watched_step_ids(store):
    return {s.watched_step for s in store.all_steps() if s.watched_step}
