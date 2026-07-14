def format_pin(origin, name, sha):
    return "%s/%s@%s" % (origin, name, sha)


def parse_selector(value):
    if not value or "@" in value or "/" not in value:
        return None
    origin, name = value.split("/", 1)
    if not origin or not name:
        return None
    return (origin, name)


def resolve_pin(selector, sha):
    parsed = parse_selector(selector)
    if parsed is None:
        raise ValueError(
            "workflow selector %r must be fully qualified '<origin>/<name>'" % selector)
    origin, name = parsed
    return format_pin(origin, name, sha)


def parse_pin(value):
    if not value or "@" not in value:
        return None
    selector, sha = value.rsplit("@", 1)
    if not sha or "/" not in selector:
        return None
    origin, name = selector.split("/", 1)
    if not origin or not name:
        return None
    return (origin, name, sha)
