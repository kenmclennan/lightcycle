from lightcycle.domain.workflows.identity import parse_pin


def pinned_shas(store, origin):
    shas = set()
    for node in store.all_nodes():
        parsed = parse_pin(node.workflow)
        if parsed and parsed[0] == origin:
            shas.add(parsed[2])
    return shas
