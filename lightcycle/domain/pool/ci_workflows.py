import re
from dataclasses import dataclass

PR_EVENTS = ("pull_request", "pull_request_target")
PATH_EVALUATION_LIMIT = 300
_FILTER_KEYS = ("branches", "branches-ignore", "paths", "paths-ignore")
_ON_KEY = re.compile(r"""^(?:on|"on"|'on'|true)\s*:(.*)$""")
_UNSUPPORTED_GLOB = re.compile(r"[?+\[\]\\]")


class _Unparseable(Exception):
    pass


@dataclass(frozen=True)
class PrWorkflows:
    expected: tuple = ()
    unreadable: tuple = ()


def _strip_comment(line):
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _scalar(text):
    value = text.strip()
    if not value:
        raise _Unparseable("empty scalar")
    if value[0] in "\"'":
        if len(value) < 2 or value[-1] != value[0]:
            raise _Unparseable("unbalanced quote")
        return value[1:-1]
    if value[0] in "&*|>{[!%@`" or ": " in value or value.endswith(":"):
        raise _Unparseable("unsupported scalar")
    return value


def _flow_list(text):
    value = text.strip()
    if not (value.startswith("[") and value.endswith("]")):
        raise _Unparseable("unterminated flow list")
    inner = value[1:-1]
    items = []
    current = ""
    quote = None
    for ch in inner:
        if quote:
            current += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            current += ch
        elif ch in "[]{}":
            raise _Unparseable("nested flow collection")
        elif ch == ",":
            items.append(current)
            current = ""
        else:
            current += ch
    if quote:
        raise _Unparseable("unbalanced quote")
    items.append(current)
    if len(items) == 1 and not items[0].strip():
        return []
    return [_scalar(item) for item in items]


def _prepare(text):
    rows = []
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        rows.append(line)
    return rows


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _children(rows, start, indent):
    end = start
    while end < len(rows):
        row = rows[end]
        if _indent(row) > indent or (_indent(row) == indent and row.lstrip().startswith("- ")):
            end += 1
        else:
            break
    return rows[start:end]


def _block_list(rows):
    items = []
    for row in rows:
        stripped = row.strip()
        if not stripped.startswith("- "):
            raise _Unparseable("not a block list")
        items.append(_scalar(stripped[2:]))
    return items


def _split_key(row):
    stripped = row.strip()
    key, sep, rest = stripped.partition(":")
    if not sep:
        raise _Unparseable("expected a mapping key")
    key = key.strip()
    if key and key[0] in "\"'":
        key = _scalar(key)
    return key, rest.strip()


def _list_value(inline, children):
    if inline:
        if children:
            raise _Unparseable("list value with trailing lines")
        return _flow_list(inline)
    items = _block_list(children)
    if not items:
        raise _Unparseable("empty list")
    return items


def _event_filters(inline, children):
    if inline and inline not in ("null", "~"):
        raise _Unparseable("event value is not a block mapping")
    filters = {}
    i = 0
    if not children:
        return filters
    base = _indent(children[0])
    while i < len(children):
        row = children[i]
        if _indent(row) != base or row.lstrip().startswith("- "):
            raise _Unparseable("unexpected line in event")
        key, rest = _split_key(row)
        nested = _children(children, i + 1, base)
        i += 1 + len(nested)
        if key in _FILTER_KEYS:
            if key in filters:
                raise _Unparseable("duplicate filter")
            filters[key] = _list_value(rest, nested)
    return filters


def _parse_on(rows):
    heads = [
        (i, m) for i, row in enumerate(rows)
        if _indent(row) == 0 and not row.startswith("-")
        for m in [_ON_KEY.match(row)] if m
    ]
    if len(heads) != 1:
        raise _Unparseable("missing or duplicate on")
    index, match = heads[0]
    inline = match.group(1).strip()
    body = _children(rows, index + 1, 0)
    if any("\t" in row for row in body) or "\t" in rows[index]:
        raise _Unparseable("tab character")
    if inline:
        if body:
            raise _Unparseable("inline on with a block")
        if inline.startswith("["):
            return {event: {} for event in _flow_list(inline)}
        return {_scalar(inline): {}}
    if not body:
        raise _Unparseable("empty on")
    if body[0].lstrip().startswith("- "):
        return {event: {} for event in _block_list(body)}
    base = _indent(body[0])
    events = {}
    i = 0
    while i < len(body):
        row = body[i]
        if _indent(row) != base or row.lstrip().startswith("- "):
            raise _Unparseable("unexpected line in on")
        key, rest = _split_key(row)
        nested = _children(body, i + 1, base)
        i += 1 + len(nested)
        if key in events:
            raise _Unparseable("duplicate event")
        if key in PR_EVENTS:
            events[key] = _event_filters(rest, nested)
        elif rest.startswith(("&", "*", "|", ">")):
            raise _Unparseable("unsupported value")
        else:
            events[key] = {}
    return events


def _glob_regex(pattern):
    if _UNSUPPORTED_GLOB.search(pattern):
        raise _Unparseable("unsupported glob")
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out)


def _ordered_match(patterns, value):
    matched = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        regex = _glob_regex(pattern[1:] if negated else pattern)
        if regex.fullmatch(value):
            matched = not negated
    return matched


def _admits(filters, base, changed):
    if "branches" in filters and not _ordered_match(filters["branches"], base):
        return False
    if "branches-ignore" in filters and _ordered_match(filters["branches-ignore"], base):
        return False
    if len(changed) >= PATH_EVALUATION_LIMIT:
        for key in ("paths", "paths-ignore"):
            for pattern in filters.get(key, ()):
                _glob_regex(pattern[1:] if pattern.startswith("!") else pattern)
        return True
    if "paths" in filters and not any(_ordered_match(filters["paths"], f) for f in changed):
        return False
    if "paths-ignore" in filters and all(_ordered_match(filters["paths-ignore"], f) for f in changed):
        return False
    return True


def _should_run(text, base, changed):
    events = _parse_on(_prepare(text))
    admitted = False
    for event in PR_EVENTS:
        if event in events and _admits(events[event], base, changed):
            admitted = True
    return admitted


def pr_workflows_expected(files, base, changed):
    expected = []
    unreadable = []
    for workflow in files:
        if workflow.text is None:
            expected.append(workflow.name)
            unreadable.append(workflow.name)
            continue
        try:
            runs = _should_run(workflow.text, base, changed)
        except _Unparseable:
            expected.append(workflow.name)
            unreadable.append(workflow.name)
            continue
        if runs:
            expected.append(workflow.name)
    return PrWorkflows(expected=tuple(expected), unreadable=tuple(unreadable))
