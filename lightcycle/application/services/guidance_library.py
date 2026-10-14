from lightcycle.domain.guidance.guidance import ENTRY, MALFORMED, classify
from lightcycle.frontmatter import split_frontmatter
from lightcycle.ports.git import GitReadError

NO_REF_ENTRY = "guidance"


def _unclosed(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    return not any(line.strip() == "---" for line in lines[1:])


class GuidanceLibrary:
    def __init__(self, git):
        self._git = git

    def ref(self, root):
        return self._git.default_ref(root)

    def has_origin(self, root):
        try:
            return self._git.remote_url(root) is not None
        except GitReadError:
            return False

    def no_ref_reason(self, root):
        if self.has_origin(root):
            return "origin has not been fetched yet - delivery has nothing to read until the pool ticks"
        return "no default branch found"

    def files(self, root):
        ref = self.ref(root)
        if ref is None:
            return []
        return self._git.list_files_at(root, ref)

    def load(self, root):
        ref = self.ref(root)
        if ref is None:
            return [], [(NO_REF_ENTRY, self.no_ref_reason(root))]
        entries, problems = [], []
        for rel in self._git.list_files_at(root, ref):
            if not rel.endswith(".md") or rel.rsplit("/", 1)[-1] == "index.md":
                continue
            entry_id = rel[: -len(".md")]
            raw = self._git.read_file_at(root, ref, rel)
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
