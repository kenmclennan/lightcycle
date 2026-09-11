import os
from collections import namedtuple

from lightcycle.domain.work import ProjectIdentity
from lightcycle.ports.git import GitReadError


ScanCandidate = namedtuple(
    "ScanCandidate",
    "identity path shortcode status remote registered_path registered_shortcode",
)

_NOISE_DIRS = {"node_modules"}


class ScanProjectsUseCase:
    def __init__(self, store, git, config, fs):
        self._store = store
        self._git = git
        self._config = config
        self._fs = fs

    def execute(self, directory):
        root = os.path.abspath(directory or ".")
        data_home = os.path.realpath(self._config.data_root())
        return self._walk(root, data_home, set())

    def _walk(self, path, data_home, seen):
        real = os.path.realpath(path)
        if real in seen or real == data_home:
            return []
        seen.add(real)
        if self._git.is_repo_root(path):
            return [self._candidate(path)]
        candidates = []
        for name in self._fs.list_dir(path):
            if name.startswith(".") or name in _NOISE_DIRS:
                continue
            candidates.extend(self._walk(os.path.join(path, name), data_home, seen))
        return candidates

    def _candidate(self, path):
        try:
            remote = self._git.remote_url(path)
        except GitReadError:
            return ScanCandidate(
                identity=None, path=path, shortcode=None, status="unreadable", remote=None,
                registered_path=None, registered_shortcode=None,
            )
        parsed = ProjectIdentity.from_remote_url(remote)
        if parsed is None:
            return ScanCandidate(
                identity=None, path=path, shortcode=None, status="no-remote", remote=remote,
                registered_path=None, registered_shortcode=None,
            )
        identity = parsed.full
        shortcode = parsed.default_shortcode
        existing = self._store.get_project(identity)
        if existing:
            return ScanCandidate(
                identity=identity, path=path, shortcode=shortcode, status="already-registered",
                remote=remote, registered_path=existing.local_path,
                registered_shortcode=existing.shortcode,
            )
        return ScanCandidate(
            identity=identity, path=path, shortcode=shortcode, status="new", remote=remote,
            registered_path=None, registered_shortcode=None,
        )
