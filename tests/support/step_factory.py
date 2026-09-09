def create_owned_step(store, title, **kw):
    if kw.get("parent") is None:
        kw["parent"] = store.create_item(title, "an owning item")
    return store.create_step(title, **kw)
