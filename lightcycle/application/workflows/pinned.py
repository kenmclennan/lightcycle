from lightcycle.domain.workflows.identity import parse_pin


def pinned_shas(store, origin):
    shas = set()
    for item in store.all_items():
        parsed = parse_pin(item.workflow)
        if parsed and parsed[0] == origin:
            shas.add(parsed[2])
    return shas
