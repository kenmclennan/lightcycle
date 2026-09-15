from lightcycle.domain.work import Item, ProjectIdentity
from lightcycle.ports.store import NodeNotFoundError


def _field_of(store, node, field):
    if isinstance(node, Item):
        return getattr(node, field)
    if isinstance(node, str):
        item_id = node
    else:
        item_id = getattr(node, "item", None) or node.id
    try:
        return getattr(store.get_item(item_id), field)
    except NodeNotFoundError:
        return None


def project_of(store, node):
    return _field_of(store, node, "project")


def repo_of(store, node):
    return _field_of(store, node, "repo")


def short_project_label(raw):
    return ProjectIdentity.short_name(raw) if raw else ""


def short_repo_label(raw):
    return ProjectIdentity.short_name(raw) if raw else ""
