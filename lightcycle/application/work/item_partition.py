from lightcycle.domain.work import State


def is_backlogged_item(store, item):
    if item.state not in (State.BACKLOGGED, State.BLOCKED):
        return False
    return item.state == State.BACKLOGGED or not store.children(item.id)


def is_closed_item(item):
    return item.state == State.DONE
