def project_of(store, node):
    if isinstance(node, str):
        item_id = node
    else:
        item_id = getattr(node, "item", None) or node.id
    try:
        return store.get_item(item_id).repo
    except Exception:
        return None


def short_project_label(raw):
    return raw.rsplit("/", 1)[-1] if raw else ""
