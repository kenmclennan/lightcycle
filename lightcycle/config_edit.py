_INDENT = "  "


def _with_newline(line):
    return line if line.endswith("\n") else line + "\n"


def _top_key(line):
    if not line or line[0] in " \t" or ":" not in line:
        return None
    return line.split(":", 1)[0].strip()


def _is_header(line, name):
    return _top_key(line) == name and not line.split(":", 1)[1].strip()


def _inner_key(line):
    if not line.strip() or ":" not in line:
        return None
    return line.split(":", 1)[0].strip()


def _spans(lines, name):
    spans = []
    for i, line in enumerate(lines):
        if not _is_header(line, name):
            continue
        end = i + 1
        while end < len(lines) and (not lines[end].strip() or lines[end][0] in " \t"):
            end += 1
        while end > i + 1 and not lines[end - 1].strip():
            end -= 1
        spans.append((i, end))
    return spans


def set_top_level(lines, key, value):
    lines = list(lines)
    hits = [i for i, line in enumerate(lines) if _top_key(line) == key]
    new = "%s: %s\n" % (key, value)
    if not hits:
        if lines:
            lines[-1] = _with_newline(lines[-1])
        return lines + [new]
    lines[hits[-1]] = new
    return [line for i, line in enumerate(lines) if i not in hits[:-1]]


def set_block_key(lines, block, key, value):
    lines = list(lines)
    spans = _spans(lines, block)
    if not spans:
        if lines:
            lines[-1] = _with_newline(lines[-1])
        return lines + ["%s:\n" % block, "%s%s: %s\n" % (_INDENT, key, value)]
    start, end = spans[-1]
    hits = [i for i in range(start + 1, end) if _inner_key(lines[i]) == key]
    if hits:
        last = lines[hits[-1]]
        indent = last[: len(last) - len(last.lstrip())]
        lines[hits[-1]] = "%s%s: %s\n" % (indent, key, value)
        return [line for i, line in enumerate(lines) if i not in hits[:-1]]
    lines[end - 1] = _with_newline(lines[end - 1])
    lines.insert(end, "%s%s: %s\n" % (_INDENT, key, value))
    return lines


def unset_block_key(lines, block, key):
    lines = list(lines)
    spans = _spans(lines, block)
    if not spans:
        return lines
    start, end = spans[-1]
    drop = {i for i in range(start + 1, end) if _inner_key(lines[i]) == key}
    if not drop:
        return lines
    remaining = [i for i in range(start + 1, end) if i not in drop and lines[i].strip()]
    if not remaining:
        drop |= set(range(start, end))
    return [line for i, line in enumerate(lines) if i not in drop]


def unset_block(lines, block):
    lines = list(lines)
    drop = set()
    for start, end in _spans(lines, block):
        drop |= set(range(start, end))
    return [line for i, line in enumerate(lines) if i not in drop]


def _same(a, b, casefold):
    return a.casefold() == b.casefold() if casefold else a == b


def list_with(stored, token, casefold):
    tokens = stored.split()
    if any(_same(t, token, casefold) for t in tokens):
        return None
    return " ".join(tokens + [token])


def list_without(stored, token, casefold):
    tokens = stored.split()
    kept = [t for t in tokens if not _same(t, token, casefold)]
    if len(kept) == len(tokens):
        return None
    return " ".join(kept)
