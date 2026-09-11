import re

_STEP_RE = re.compile(r"^(.+)-(\d+)\.(\d+)$")
_ITEM_RE = re.compile(r"^(.+)-(\d+)$")


def node_id_key(node_id):
    m = _STEP_RE.match(node_id)
    if m:
        prefix, item_n, step_n = m.groups()
        return (prefix, int(item_n), int(step_n))
    m = _ITEM_RE.match(node_id)
    if m:
        prefix, item_n = m.groups()
        return (prefix, int(item_n), -1)
    return (node_id, -1, -1)


def format_step_id(item_id, n):
    return "%s.%d" % (item_id, n)
