from lightcycle.application.work import automation
from lightcycle.domain.work import State, parse_timestamp


def closed_count(store, day):
    count = 0
    for item in store.all_items_including_done():
        if item.state != State.DONE:
            continue
        closed = parse_timestamp(item.closed_at)
        if closed is None or closed.date() != day:
            continue
        if automation.AUTOMATION_LABELS.intersection(store.labels_of(item.id)):
            continue
        count += 1
    return count
