WORKER_VERBS = ("claim", "done", "show", "attach", "retro", "backlog", "search", "peek")

_SET_FORBIDDEN_FIELDS = (
    "title", "description", "project", "workflow", "backlog", "label", "step", "unset",
)

_ATTACH_FORBIDDEN_TYPES = ("repo",)


def worker_permitted(verb, parsed_flags):
    if verb == "attach":
        return parsed_flags.get("type") not in _ATTACH_FORBIDDEN_TYPES
    if verb in WORKER_VERBS:
        return True
    if verb == "set":
        if any(parsed_flags.get(f) for f in _SET_FORBIDDEN_FIELDS):
            return False
        return parsed_flags.get("state") == "waiting"
    if verb == "workflow":
        return parsed_flags.get("sub") == "check" and bool(parsed_flags.get("dir"))
    return False


def worker_refusal_message(verb):
    if verb == "attach":
        return "lc: workers may not attach an artifact of type %s - attach is otherwise permitted\n" % (
            ", ".join(_ATTACH_FORBIDDEN_TYPES),
        )
    return "lc: workers may not run '%s' - permitted: %s, set --state waiting, workflow check --dir\n" % (
        verb, ", ".join(WORKER_VERBS),
    )
