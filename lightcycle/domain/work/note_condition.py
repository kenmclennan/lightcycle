import re

_CONDITION_RE = re.compile(r"^(?P<text>.*) \(x(?P<count>\d+), last .*\)$")


def merge_condition_note(existing, text, now):
    normalized = " ".join(text.split())
    lines = existing.splitlines() if existing else []
    last = lines[-1] if lines else None
    match = _CONDITION_RE.match(last) if last else None
    if match and match.group("text") == normalized:
        count = int(match.group("count")) + 1
        lines[-1] = "%s (x%d, last %s)" % (normalized, count, now)
    else:
        lines.append("%s (x1, last %s)" % (normalized, now))
    return "\n".join(lines)
