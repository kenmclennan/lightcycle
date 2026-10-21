WORKER_VERBS = ("claim", "done", "show", "attach", "retro", "backlog", "search", "peek",
                "guidance", "guidance-dir", "guidance-check",
                "guidance-conventions")

_SET_FORBIDDEN_FIELDS = (
    "title", "description", "project", "workflow", "backlog", "label", "step", "unset",
)

ATTACH_FORBIDDEN_TYPES = ("repo", "resolves", "resolved-by")


def worker_permitted(verb, parsed_flags):
    if verb == "attach":
        return parsed_flags.get("type") not in ATTACH_FORBIDDEN_TYPES
    if verb in WORKER_VERBS:
        return True
    if verb == "set":
        if any(parsed_flags.get(f) for f in _SET_FORBIDDEN_FIELDS):
            return False
        return parsed_flags.get("state") == "waiting"
    if verb == "workflow":
        if parsed_flags.get("sub") == "list":
            return True
        return parsed_flags.get("sub") == "check" and bool(parsed_flags.get("dir"))
    if verb == "config":
        return "edit" in parsed_flags and not parsed_flags["edit"]
    return False

