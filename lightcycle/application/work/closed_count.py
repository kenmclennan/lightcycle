from lightcycle.application.flow.engine_steps import RETRO_ORIGIN_LABEL, SUMMARY_ORIGIN_LABEL
from lightcycle.domain.work import State, parse_timestamp

_INTERNAL_LABELS = frozenset({SUMMARY_ORIGIN_LABEL, RETRO_ORIGIN_LABEL})


def closed_count(store, day):
    count = 0
    for item in store.all_items_including_done():
        if item.state != State.DONE:
            continue
        closed = parse_timestamp(item.closed_at)
        if closed is None or closed.date() != day:
            continue
        if _INTERNAL_LABELS.intersection(store.labels_of(item.id)):
            continue
        count += 1
    return count
