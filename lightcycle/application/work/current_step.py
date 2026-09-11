from lightcycle.domain.work import State


def current_step(store, item_id):
    for child in store.children(item_id):
        if child.state != State.DONE:
            return child
    return None
