"""Pure artifact contracts and the static flow-composition analysis."""

# Artifact types tg file attaches to a freshly filed story; the entry budget.
FILE_PROVIDES = {"spec"}


def artifact_types(meta, key):
    """Frontmatter accepts/produces block -> {type: required_bool}."""
    d = meta.get(key)
    if not isinstance(d, dict):
        return {}
    return {t: str(v).strip().lower() != "optional" for t, v in d.items()}


def required_inputs(meta):
    return {t for t, req in artifact_types(meta, "accepts").items() if req}


def optional_inputs(meta):
    return {t for t, req in artifact_types(meta, "accepts").items() if not req}


def required_outputs(meta):
    return {t for t, req in artifact_types(meta, "produces").items() if req}


def guaranteed_artifacts(steps, routes, prod, entries):
    """Greatest fixpoint: artifact types guaranteed present when each step starts.

    A step's guaranteed set is the intersection over its incoming contexts: the
    entry context (FILE_PROVIDES, if the step can be filed) plus, per route edge
    A -> step, A's guaranteed set unioned with what A produces. Intersection (not
    union) means 'present on every path', so rework targets stay honest.
    """
    universe = set().union(FILE_PROVIDES, *prod.values()) if steps else set()
    incoming = {s: [] for s in steps}
    for src in steps:
        for nxt in routes.get(src, {}).values():
            if nxt in incoming:
                incoming[nxt].append(src)
    ga = {s: set(universe) for s in steps}
    for _ in range(len(steps) + 2):
        for s in steps:
            ctxs = []
            if s in entries:
                ctxs.append(set(FILE_PROVIDES))
            for src in incoming[s]:
                ctxs.append(ga[src] | prod[src])
            ga[s] = set(universe) if not ctxs else set.intersection(*ctxs)
    return ga


def analyze_flow(owner, routes, role_metas):
    """Static analysis of an assembled flow. Returns a dict of derived facts.

    owner/routes come from flow.load_flow; role_metas maps every role -> meta
    (used for the per-step contracts and for duplicate-step-owner detection).
    Contracts are read from the file that declares the step, not from owner: a
    human step's owner is the literal "human", but its accepts/produces still
    live in its own frontmatter.
    """
    declarer, dups = {}, []
    for role in sorted(role_metas):
        step = (role_metas[role] or {}).get("step")
        if not step:
            continue
        if step in declarer:
            dups.append("step '%s' owned by both %s and %s" % (step, declarer[step], role))
        else:
            declarer[step] = role
    steps = sorted(owner)
    step_meta = {s: (role_metas.get(declarer.get(s)) or {}) for s in steps}
    req = {s: required_inputs(step_meta[s]) for s in steps}
    opt = {s: optional_inputs(step_meta[s]) for s in steps}
    prod = {s: required_outputs(step_meta[s]) for s in steps}
    entries = [s for s in steps if req[s] <= FILE_PROVIDES]
    ga = guaranteed_artifacts(steps, routes, prod, entries)

    reach, stack = set(), list(entries)
    while stack:
        s = stack.pop()
        if s in reach:
            continue
        reach.add(s)
        stack += [n for n in routes.get(s, {}).values() if n in owner]
    unreachable = [s for s in steps if s not in reach]
    missing = {s: sorted(req[s] - ga[s]) for s in steps if s in reach and req[s] - ga[s]}

    targets = set()
    for rmap in routes.values():
        targets.update(rmap.values())
    terminals = sorted(t for t in targets if t not in owner)

    ok = not missing and not dups
    return {"steps": steps, "req": req, "opt": opt, "prod": prod,
            "entries": entries, "unreachable": unreachable, "missing": missing,
            "terminals": terminals, "dups": dups, "ok": ok}
