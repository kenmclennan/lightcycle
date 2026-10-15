from lightcycle.application.errors import UseCaseError
from lightcycle.domain.guidance.conventions import check_entries, is_checked_path
from lightcycle.ports.git import GitReadError


def _text(raw):
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


class CheckGuidanceUseCase:

    def __init__(self, git, fs):
        self._git = git
        self._fs = fs

    def execute(self, directory, mode, base):
        try:
            rows = self._git.changed_paths(directory, base)
        except GitReadError as e:
            raise UseCaseError(str(e))
        changed, deleted = [], []
        for status, path in rows:
            if not is_checked_path(path):
                continue
            (deleted if status == "D" else changed).append(path)

        def read_head(path):
            raw = self._fs.read_bytes("%s/%s" % (directory, path))
            if raw is None:
                raise UseCaseError("cannot read %s in %s" % (path, directory))
            return _text(raw)

        def read_base(path):
            raw = self._git.read_file_at(directory, base, path)
            return None if raw is None else _text(raw)

        for path in deleted:
            if read_base(path) is None:
                raise UseCaseError("cannot read %s at %s in %s" % (path, base, directory))

        facet_pages = {
            rel.rsplit("/", 1)[-1][:-3]
            for rel in self._fs.list_files(directory)
            if rel.endswith(".md")
        }
        failures = check_entries(mode, changed, deleted, facet_pages, read_head, read_base)
        return failures, len(changed)
