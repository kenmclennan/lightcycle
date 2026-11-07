def _joined_list(block):
    if not block or not block[0].startswith("["):
        return None
    text = " ".join(block)
    if not text.endswith("]"):
        return None
    entries = [e.strip() for e in text[1:-1].split(",")]
    return "[" + ", ".join(e for e in entries if e) + "]"


def parse_frontmatter(text):
    meta = {}
    pending = None
    block = []

    def settle():
        joined = _joined_list(block)
        if joined is not None:
            meta[pending] = joined

    for fl in text.splitlines():
        if not fl.strip():
            continue
        if fl[0] in " \t" and pending is not None:
            block.append(fl.strip())
            if not block[0].startswith("[") and ":" in fl:
                k, v = fl.split(":", 1)
                meta[pending][k.strip()] = v.strip()
            continue
        if pending is not None:
            settle()
        pending = None
        block = []
        if ":" not in fl:
            continue
        k, v = fl.split(":", 1)
        k, v = k.strip(), v.strip()
        if v == "":
            meta[k] = {}
            pending = k
        else:
            meta[k] = v
    if pending is not None:
        settle()
    return meta


def split_frontmatter(text):
    meta, body = {}, text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                meta = parse_frontmatter("\n".join(lines[1:i]))
                body = "\n".join(lines[i + 1 :]).lstrip("\n")
                break
    return meta, body
