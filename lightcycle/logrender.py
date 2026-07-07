import json


def render_log_line(line):
    line = line.rstrip("\n")
    if not line.strip():
        return None
    try:
        e = json.loads(line)
    except Exception:
        return line
    t = e.get("type")
    if t == "assistant":
        out = []
        for c in e.get("message", {}).get("content") or []:
            if c.get("type") == "text" and c.get("text", "").strip():
                out.append(c["text"].rstrip())
            elif c.get("type") == "tool_use":
                inp = c.get("input") or {}
                if c.get("name") == "Bash":
                    out.append("$ " + (inp.get("command") or "").strip())
                else:
                    arg = inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
                    label = ("%s %s" % (c.get("name", "tool"), arg)).rstrip()
                    out.append("[%s]" % label)
        return "\n".join(out) if out else None
    if t == "user":
        for c in e.get("message", {}).get("content") or []:
            if c.get("type") == "tool_result":
                r = c.get("content")
                if isinstance(r, list):
                    r = " ".join(x.get("text", "") for x in r if isinstance(x, dict))
                first = ((r or "").strip().splitlines() or [""])[0]
                return "  -> " + first[:200] if first else None
        return None
    if t == "result":
        return ">>> " + (e.get("result") or "").strip()
    return None
