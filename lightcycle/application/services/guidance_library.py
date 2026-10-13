from lightcycle.domain.guidance.guidance import ENTRY, MALFORMED, classify
from lightcycle.frontmatter import split_frontmatter


def _unclosed(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    return not any(line.strip() == "---" for line in lines[1:])


class GuidanceLibrary:
    def __init__(self, fs):
        self._fs = fs

    def load(self, root):
        entries, problems = [], []
        for rel in self._fs.list_files(root):
            if not rel.endswith(".md") or rel.rsplit("/", 1)[-1] == "index.md":
                continue
            entry_id = rel[: -len(".md")]
            raw = self._fs.read_bytes("%s/%s" % (root.rstrip("/"), rel))
            if raw is None:
                problems.append((entry_id, "file could not be read"))
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                problems.append((entry_id, "file is not valid UTF-8"))
                continue
            if _unclosed(text):
                problems.append((entry_id, "front matter is opened but never closed"))
                continue
            meta, body = split_frontmatter(text)
            result = classify(entry_id, meta, body)
            if result.kind == MALFORMED:
                problems.append((entry_id, result.reason))
            elif result.kind == ENTRY:
                entries.append(result.entry)
        return entries, problems
