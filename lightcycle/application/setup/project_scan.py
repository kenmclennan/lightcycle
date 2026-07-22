import os
import re
from collections import namedtuple


ScanCandidate = namedtuple(
    "ScanCandidate",
    "identity path shortcode status remote registered_path registered_shortcode",
)

_NOISE_DIRS = {"node_modules"}

_SSH_RE = re.compile(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?/?$")
_HTTPS_RE = re.compile(r"^https://github\.com/([^/]+)/(.+?)(?:\.git)?/?$")


def _identity_from_remote(remote):
    if not remote:
        return None
    for pattern in (_SSH_RE, _HTTPS_RE):
        m = pattern.match(remote.strip())
        if m:
            return "%s/%s" % (m.group(1), m.group(2))
    return None


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
        if self._git.is_git_repo(path):
            return [self._candidate(path)]
        candidates = []
        for name in self._fs.list_dir(path):
            if name.startswith(".") or name in _NOISE_DIRS:
                continue
            candidates.extend(self._walk(os.path.join(path, name), data_home, seen))
        return candidates

    def _candidate(self, path):
        remote = self._git.remote_url(path)
        identity = _identity_from_remote(remote)
        if identity is None:
            return ScanCandidate(
                identity=None, path=path, shortcode=None, status="no-remote", remote=remote,
                registered_path=None, registered_shortcode=None,
            )
        shortcode = identity.split("/")[-1].upper()
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
