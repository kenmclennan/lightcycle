def order_stacks(entries, item_of, parent_of):
    items_with_rows = {item_of(e) for e in entries}

    def nearest_ancestor(item):
        seen = {item}
        parent = parent_of(item)
        while parent and parent not in seen:
            if parent in items_with_rows:
                return parent
            seen.add(parent)
            parent = parent_of(parent)
        return None

    rows_of = {}
    children = {}
    roots = []
    for e in entries:
        item = item_of(e)
        if item not in rows_of:
            rows_of[item] = []
            ancestor = nearest_ancestor(item)
            if ancestor is None:
                roots.append(item)
            else:
                children.setdefault(ancestor, []).append(item)
        rows_of[item].append(e)

    ordered = []
    emitted = set()

    def emit(item):
        if item in emitted:
            return
        emitted.add(item)
        ordered.extend(rows_of[item])
        for child in children.get(item, ()):
            emit(child)

    for item in roots:
        emit(item)
    for item in rows_of:
        emit(item)
    return ordered
