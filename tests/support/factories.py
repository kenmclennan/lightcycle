from lightcycle.domain.work import Item, Park, Step

_PARK_KEYS = ("reason", "needs", "tried")


def make_step(**kw):
    kw.pop("type", None)
    kw.pop("artifacts", None)
    kw.pop("description", None)
    kw.pop("project", None)
    kw.pop("goal", None)
    kw.pop("attention", None)
    kw.pop("since", None)
    kw.pop("branch", None)
    kw.pop("pr", None)
    kw.pop("workflow", None)
    if "step" in kw:
        kw["stage"] = kw.pop("step")
    if "parent" in kw:
        kw["item"] = kw.pop("parent")
    park = {k: kw.pop(k) for k in _PARK_KEYS if k in kw}
    kw.setdefault("id", "s-1")
    kw.setdefault("item", "i-1")
    if park:
        kw["park"] = Park(**park)
    return Step(**kw)


def make_item(**kw):
    kw.pop("type", None)
    kw.pop("role", None)
    kw.pop("step", None)
    kw.pop("parent", None)
    kw.pop("goal", None)
    kw.pop("attention", None)
    kw.setdefault("id", "i-1")
    if "artifacts" in kw:
        kw["artifacts"] = tuple(kw["artifacts"])
    return Item(**kw)
