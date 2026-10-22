from lightcycle.domain.workflows.lifecycle import script_path_shape_problem

PENDING_REFLECTIONS = "pending-reflections"
MATERIALS_CHANGED = "materials-changed"
DAY_UNSUMMARISED = "day-unsummarised"
REPOS_ACTIVE = "repos-active"

_GUARD_PARAMETERS = {
    PENDING_REFLECTIONS: (("min", True),),
    MATERIALS_CHANGED: (),
    DAY_UNSUMMARISED: (),
    REPOS_ACTIVE: (),
}


SCRIPT_GUARD_PREFIX = "script:"


def is_script_guard(name):
    return bool(name) and name.startswith(SCRIPT_GUARD_PREFIX)


def script_guard_path(name):
    return name[len(SCRIPT_GUARD_PREFIX):].strip()


def guard_names():
    return tuple(_GUARD_PARAMETERS)


def parse_guard_params(name, raw):
    if is_script_guard(name):
        problem = script_path_shape_problem("script guard", script_guard_path(name))
        if problem:
            raise ValueError(problem)
        return dict(raw)
    if name not in _GUARD_PARAMETERS:
        raise ValueError("unknown guard %r; the engine has: %s" % (name, ", ".join(guard_names())))
    schema = dict(_GUARD_PARAMETERS[name])
    unknown = sorted(set(raw) - set(schema))
    if unknown:
        raise ValueError("guard %s has no parameter %s" % (name, ", ".join(unknown)))
    params = {}
    for key, required in schema.items():
        if key not in raw:
            if required:
                raise ValueError("guard %s needs parameter %s" % (name, key))
            continue
        text = str(raw[key]).strip()
        if not text.isdigit() or int(text) < 1:
            raise ValueError("guard %s parameter %s must be an integer of at least 1 (got %r)"
                             % (name, key, raw[key]))
        params[key] = int(text)
    return params

RETIRED_JOB_SCHEDULES = (
    ("retro-audit", "lightcycle/retro-audit"),
    ("material-audit", "lightcycle/material-audit"),
    ("daily-summary", "lightcycle/daily-summary"),
)
