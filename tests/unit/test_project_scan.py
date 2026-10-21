import os
import tempfile
import unittest

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.application.setup.project_scan import ScanProjectsUseCase
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore


class _Cfg:
    def __init__(self, data_root):
        self._data_root = data_root

    def data_root(self):
        return self._data_root


class TestScanProjects(unittest.TestCase):
    def test_no_repos_anywhere_returns_empty(self):
        root = "/tree"
        fs = FakeFs(dirs={root: ["a", "b"]})
        uc = ScanProjectsUseCase(FakeStore(), FakeGit(repos=()), _Cfg("/nonexistent"), fs)
        self.assertEqual(uc.execute(root).candidates, [])

    def test_repo_with_ssh_remote_is_new(self):
        root = "/tree/x"
        git = FakeGit(repos={root}, origin={root: "git@github.com:acme/x.git"})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), FakeFs())
        [cand] = uc.execute(root).candidates
        self.assertEqual(cand.identity, "acme/x")
        self.assertEqual(cand.shortcode, "X")
        self.assertEqual(cand.status, "new")

    def test_repo_with_https_remote_with_and_without_git_suffix(self):
        for remote in ("https://github.com/acme/x", "https://github.com/acme/x.git"):
            root = "/tree/x"
            git = FakeGit(repos={root}, origin={root: remote})
            uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), FakeFs())
            [cand] = uc.execute(root).candidates
            self.assertEqual(cand.identity, "acme/x")

    def test_repo_with_no_origin_is_no_remote(self):
        root = "/tree/x"
        git = FakeGit(repos={root})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), FakeFs())
        [cand] = uc.execute(root).candidates
        self.assertEqual(cand.status, "no-remote")
        self.assertIsNone(cand.identity)
        self.assertIsNone(cand.remote)

    def test_repo_with_non_github_remote_is_no_remote_but_remote_preserved(self):
        root = "/tree/x"
        git = FakeGit(repos={root}, origin={root: "git@gitlab.com:acme/x.git"})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), FakeFs())
        [cand] = uc.execute(root).candidates
        self.assertEqual(cand.status, "no-remote")
        self.assertIsNone(cand.identity)
        self.assertEqual(cand.remote, "git@gitlab.com:acme/x.git")

    def test_unreadable_repo_is_reported_distinctly_and_does_not_abort_the_walk(self):
        root = "/tree"
        broken = os.path.join(root, "broken")
        ok = os.path.join(root, "ok")
        fs = FakeFs(dirs={root: ["broken", "ok"]})
        git = FakeGit(
            repos={broken, ok}, origin={ok: "git@github.com:acme/ok.git"},
            remote_unreadable={broken},
        )
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), fs)
        candidates = uc.execute(root).candidates
        by_path = {c.path: c for c in candidates}
        self.assertEqual(len(candidates), 2)
        self.assertEqual(by_path[broken].status, "unreadable")
        self.assertIsNone(by_path[broken].identity)
        self.assertEqual(by_path[ok].status, "new")

    def test_already_registered_shows_found_and_registered_separately(self):
        root = "/tree/x"
        store = FakeStore()
        store.add_project("acme/x", shortcode="OLD", local_path="/elsewhere")
        git = FakeGit(repos={root}, origin={root: "git@github.com:acme/x.git"})
        uc = ScanProjectsUseCase(store, git, _Cfg("/nonexistent"), FakeFs())
        [cand] = uc.execute(root).candidates
        self.assertEqual(cand.status, "already-registered")
        self.assertEqual(cand.path, root)
        self.assertEqual(cand.registered_path, "/elsewhere")
        self.assertEqual(cand.registered_shortcode, "OLD")

    def test_prunes_at_a_repo_boundary(self):
        root = "/tree"
        sub = os.path.join(root, "sub")
        fs = FakeFs(dirs={root: ["sub"]})
        git = FakeGit(repos={root, sub})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), fs)
        candidates = uc.execute(root).candidates
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].path, root)

    def test_hidden_directory_is_never_descended_into(self):
        root = "/tree"
        hidden = os.path.join(root, ".hidden")
        nested = os.path.join(hidden, "repo")
        fs = FakeFs(dirs={root: [".hidden"], hidden: ["repo"]})
        git = FakeGit(repos={nested})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), fs)
        self.assertEqual(uc.execute(root).candidates, [])

    def test_node_modules_is_skipped_the_same_way(self):
        root = "/tree"
        nm = os.path.join(root, "node_modules")
        nested = os.path.join(nm, "repo")
        fs = FakeFs(dirs={root: ["node_modules"], nm: ["repo"]})
        git = FakeGit(repos={nested})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), fs)
        self.assertEqual(uc.execute(root).candidates, [])

    def test_configured_data_home_is_skipped_even_mid_tree(self):
        root = "/tree"
        state = os.path.join(root, "state")
        app = os.path.join(root, "app")
        nested = os.path.join(state, "repo")
        fs = FakeFs(dirs={root: ["state", "app"], app: []})
        git = FakeGit(repos={nested})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg(state), fs)
        self.assertEqual(uc.execute(root).candidates, [])

    def test_multiple_nested_candidates_mixed_statuses(self):
        root = "/tree"
        new_repo = os.path.join(root, "new")
        reg_repo = os.path.join(root, "registered")
        noremote_repo = os.path.join(root, "noremote")
        fs = FakeFs(dirs={root: ["new", "registered", "noremote"]})
        store = FakeStore()
        store.add_project("acme/registered", shortcode="REG", local_path="/elsewhere")
        git = FakeGit(
            repos={new_repo, reg_repo, noremote_repo},
            origin={
                new_repo: "git@github.com:acme/new.git",
                reg_repo: "git@github.com:acme/registered.git",
            },
        )
        uc = ScanProjectsUseCase(store, git, _Cfg("/nonexistent"), fs)
        candidates = uc.execute(root).candidates
        by_path = {c.path: c for c in candidates}
        self.assertEqual(len(candidates), 3)
        self.assertEqual(by_path[new_repo].status, "new")
        self.assertEqual(by_path[reg_repo].status, "already-registered")
        self.assertEqual(by_path[noremote_repo].status, "no-remote")

    def test_symlink_cycle_terminates_instead_of_recursing_forever(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "dir"))
        os.symlink(root, os.path.join(root, "dir", "loop"))
        git = FakeGit(repos=())
        config = _Cfg("/nonexistent")
        fs = FsAdapter(config)
        uc = ScanProjectsUseCase(FakeStore(), git, config, fs)
        self.assertEqual(uc.execute(root).candidates, [])


def _page(front):
    return ("---\n%s\n---\nbody\n" % front).encode()


GUIDE = "/guide"
REPO = "/tree/x"


def _suggest_env(pages, repo_files, register=True):
    store = FakeStore()
    fs = FakeFs(dirs={GUIDE: []})
    if register:
        store.add_project(GUIDANCE_WORKSPACE, local_path=GUIDE)
    git = FakeGit(
        repos={REPO}, origin={REPO: "git@github.com:acme/x.git"}, ref="main",
        ref_files={"main": pages, "HEAD": {f: b"" for f in repo_files}},
    )
    return ScanProjectsUseCase(store, git, _Cfg("/nonexistent"), fs).execute(REPO)


PAGES = {
    "languages/python.md": _page("detected-by: [pyproject.toml]"),
    "languages/markdown.md": _page("detected-by: [*.md]"),
    "patterns/hexagonal.md": _page("title: Hexagonal"),
}


class TestScanSuggestsFacets(unittest.TestCase):
    def test_matching_facet_is_suggested_with_its_file_and_the_other_is_not(self):
        result = _suggest_env(PAGES, ["pyproject.toml", "src/a.py"])
        [cand] = result.candidates
        self.assertEqual(cand.suggested_facets, (("python", "pyproject.toml"),))
        self.assertIsNone(result.no_suggestions_reason)

    def test_pattern_page_without_detected_by_is_never_suggested(self):
        result = _suggest_env(PAGES, ["pyproject.toml", "README.md", "hexagonal.md"])
        [cand] = result.candidates
        self.assertEqual(
            cand.suggested_facets, (("markdown", "README.md"), ("python", "pyproject.toml"))
        )

    def test_workspace_without_detected_by_gives_the_reason_and_no_suggestions(self):
        pages = {"languages/python.md": _page("title: Python")}
        result = _suggest_env(pages, ["pyproject.toml"])
        self.assertEqual(result.no_suggestions_reason, "no concept page carries detected-by")
        self.assertEqual(result.candidates[0].suggested_facets, ())

    def test_invalid_page_is_skipped_and_the_valid_one_still_suggests(self):
        pages = {
            "languages/python.md": _page("detected-by: [pyproject.toml]"),
            "languages/markdown.md": _page('detected-by: ["*.md"]'),
        }
        result = _suggest_env(pages, ["pyproject.toml", "README.md"])
        self.assertEqual(result.candidates[0].suggested_facets, (("python", "pyproject.toml"),))
        self.assertIsNone(result.no_suggestions_reason)

    def test_entry_carrying_detected_by_is_ignored(self):
        pages = {"testing/x.md": _page("type: Guidance\ndetected-by: [pyproject.toml]")}
        result = _suggest_env(pages, ["pyproject.toml"])
        self.assertEqual(result.candidates[0].suggested_facets, ())
        self.assertEqual(result.no_suggestions_reason, "no concept page carries detected-by")

    def test_no_registered_guidance_repo_gives_the_reason(self):
        result = _suggest_env(PAGES, ["pyproject.toml"], register=False)
        self.assertEqual(result.no_suggestions_reason, "no guidance repo is registered")
        self.assertEqual(result.candidates[0].suggested_facets, ())

    def test_unreadable_candidate_has_no_suggestions(self):
        store = FakeStore()
        store.add_project(GUIDANCE_WORKSPACE, local_path=GUIDE)
        git = FakeGit(
            repos={REPO}, remote_unreadable={REPO}, ref="main",
            ref_files={"main": PAGES, "HEAD": {"pyproject.toml": b""}},
        )
        uc = ScanProjectsUseCase(store, git, _Cfg("/nonexistent"), FakeFs(dirs={GUIDE: []}))
        [cand] = uc.execute(REPO).candidates
        self.assertEqual(cand.status, "unreadable")
        self.assertEqual(cand.suggested_facets, ())
