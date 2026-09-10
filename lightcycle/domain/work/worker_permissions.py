WORKER_VERBS = ("claim", "done", "show", "attach", "retro", "backlog", "search", "peek")

_SET_FORBIDDEN_FIELDS = (
    "title", "description", "project", "workflow", "backlog", "label", "step", "unset",
)


def worker_permitted(verb, parsed_flags):
    if verb in WORKER_VERBS:
        return True
    if verb == "set":
        if any(parsed_flags.get(f) for f in _SET_FORBIDDEN_FIELDS):
            return False
        return parsed_flags.get("state") == "waiting"
    return False


def worker_refusal_message(verb):
    return "lc: workers may not run '%s' - permitted: %s, set --state waiting\n" % (
        verb, ", ".join(WORKER_VERBS),
    )
