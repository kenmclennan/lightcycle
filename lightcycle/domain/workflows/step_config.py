from lightcycle.domain.workflows.lifecycle import KEY_SHAPE


def step_config_keys(meta):
    if "config" not in meta:
        return ()
    raw = meta["config"]
    if not isinstance(raw, str):
        raise ValueError("config: on a step is an inline list like [key, key], not a block")
    text = raw.strip()
    if not (text.startswith("[") and text.endswith("]")):
        raise ValueError("config: must be an inline list like [key, key] (got %r)" % raw)
    inner = text[1:-1].strip()
    if not inner:
        return ()
    keys = []
    for part in inner.split(","):
        key = part.strip()
        if not key:
            raise ValueError("config: list has an empty entry (got %r)" % raw)
        if not KEY_SHAPE.match(key):
            raise ValueError("config: key %r must match [a-z0-9-]+" % key)
        if key in keys:
            raise ValueError("config: key %r is listed twice" % key)
        keys.append(key)
    return tuple(keys)


def step_config_problems(workflow, stage_files, step_metas, declared_keys):
    problems = []
    declared = set(declared_keys)
    for stage, file in stage_files:
        meta = step_metas.get(file)
        if meta is None:
            continue
        label = "step '%s' (steps/%s.md)" % (stage, file)
        try:
            keys = step_config_keys(meta)
        except ValueError as e:
            problems.append("%s %s" % (label, e))
            continue
        for key in keys:
            if key not in declared:
                problems.append(
                    "%s lists config key '%s', which workflow '%s' does not declare "
                    "in its config: block" % (label, key, workflow))
    return problems
