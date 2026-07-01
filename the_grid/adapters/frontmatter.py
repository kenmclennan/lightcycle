"""Frontmatter parsing for the step and config files (a file-format detail of the
fs/config adapters, not a domain concern). Operates on text only."""


def parse_frontmatter(text):
    """Parse simple `key: value` lines, with one level of `key:` + indented block."""
    meta = {}
    pending = None
    for fl in text.splitlines():
        if not fl.strip():
            continue
        if fl[0] in " \t" and pending is not None:
            if ":" in fl:
                k, v = fl.split(":", 1)
                meta[pending][k.strip()] = v.strip()
            continue
        pending = None
        if ":" not in fl:
            continue
        k, v = fl.split(":", 1)
        k, v = k.strip(), v.strip()
        if v == "":
            meta[k] = {}
            pending = k
        else:
            meta[k] = v
    return meta


def split_frontmatter(text):
    """Split a leading --- ... --- block from the body. Returns (meta, body).

    meta is the parsed frontmatter (empty if none); body is the remaining text.
    """
    meta, body = {}, text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                meta = parse_frontmatter("\n".join(lines[1:i]))
                body = "\n".join(lines[i + 1:]).lstrip("\n")
                break
    return meta, body
