from lightcycle.domain.work import Item


def project_of(store, item):
    return Item(item.id, tuple(store.item_artifacts(item.id))).repo()


def short_project_label(raw):
    return raw.rsplit("/", 1)[-1] if raw else ""
