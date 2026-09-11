from lightcycle.domain.work import ProjectIdentity
from lightcycle.ports.store import NodeNotFoundError


def project_of(store, node):
    if isinstance(node, str):
        item_id = node
    else:
        item_id = getattr(node, "item", None) or node.id
    try:
        return store.get_item(item_id).repo
    except NodeNotFoundError:
        return None


def short_project_label(raw):
    return ProjectIdentity.short_name(raw) if raw else ""
