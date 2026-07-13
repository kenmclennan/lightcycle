from lightcycle.domain.work import Item


def project_of(store, item):
    return Item(item.id, tuple(store.item_artifacts(item.id))).repo()
