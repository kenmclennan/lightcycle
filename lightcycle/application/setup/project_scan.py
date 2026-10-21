import os
from collections import namedtuple

from lightcycle.application.services.guidance_library import GuidanceLibrary
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from lightcycle.domain.guidance.conventions import inline_list
from lightcycle.domain.guidance.detection import detect, parse_detected_by
from lightcycle.domain.work import ProjectIdentity
from lightcycle.frontmatter import split_frontmatter
from lightcycle.ports.git import GitReadError


ScanCandidate = namedtuple(
    "ScanCandidate",
    "identity path shortcode status remote registered_path registered_shortcode suggested_facets",
)

ScanResult = namedtuple("ScanResult", "candidates no_suggestions_reason")

_NOISE_DIRS = {"node_modules"}


class ScanProjectsUseCase:
    def __init__(self, store, git, config, fs):
        self._store = store
        self._git = git
        self._config = config
        self._fs = fs

    def execute(self, directory):
        root = os.path.abspath(directory or ".")
        data_home = self._fs.real_path(self._config.data_root())
        rules, reason = self._load_rules()
        candidates = self._walk(root, data_home, set(), rules)
        return ScanResult(candidates, reason)

    def _load_rules(self):
        project = self._store.get_project(GUIDANCE_WORKSPACE)
        path = project.local_path if project else None
        if not path or not self._fs.exists(path):
            return {}, "no guidance repo is registered"
        library = GuidanceLibrary(self._git)
        ref = library.ref(path)
        if ref is None:
            return {}, "the guidance repo has no default branch"
        rules = {}
        for rel in library.files(path):
            if not rel.endswith(".md") or rel.rsplit("/", 1)[-1] == "index.md":
                continue
            facet = rel.rsplit("/", 1)[-1][: -len(".md")]
            if facet in rules:
                continue
            raw = self._git.read_file_at(path, ref, rel)
            if raw is None:
                continue
            meta, _ = split_frontmatter(raw.decode("utf-8", errors="replace"))
            if meta.get("type") == "Guidance" or "detected-by" not in meta:
                continue
            elements = parse_detected_by(inline_list(meta["detected-by"]))
            if elements is not None:
                rules[facet] = elements
        if not rules:
            return {}, "no concept page carries detected-by"
        return rules, None

    def _walk(self, path, data_home, seen, rules):
        real = self._fs.real_path(path)
        if real in seen or real == data_home:
            return []
        seen.add(real)
        if self._git.is_repo_root(path):
            return [self._candidate(path, rules)]
        candidates = []
        for name in self._fs.list_dir(path):
            if name.startswith(".") or name in _NOISE_DIRS:
                continue
            candidates.extend(self._walk(os.path.join(path, name), data_home, seen, rules))
        return candidates

    def _candidate(self, path, rules):
        try:
            remote = self._git.remote_url(path)
        except GitReadError:
            return ScanCandidate(
                identity=None, path=path, shortcode=None, status="unreadable", remote=None,
                registered_path=None, registered_shortcode=None, suggested_facets=(),
            )
        suggested = self._suggest(path, rules)
        parsed = ProjectIdentity.from_remote_url(remote)
        if parsed is None:
            return ScanCandidate(
                identity=None, path=path, shortcode=None, status="no-remote", remote=remote,
                registered_path=None, registered_shortcode=None, suggested_facets=suggested,
            )
        identity = parsed.full
        shortcode = parsed.default_shortcode
        existing = self._store.get_project(identity)
        if existing:
            return ScanCandidate(
                identity=identity, path=path, shortcode=shortcode, status="already-registered",
                remote=remote, registered_path=existing.local_path,
                registered_shortcode=existing.shortcode,
                suggested_facets=suggested,
            )
        return ScanCandidate(
            identity=identity, path=path, shortcode=shortcode, status="new", remote=remote,
            registered_path=None, registered_shortcode=None, suggested_facets=suggested,
        )

    def _suggest(self, path, rules):
        if not rules:
            return ()
        return tuple(detect(rules, self._git.list_files_at(path, "HEAD")))
