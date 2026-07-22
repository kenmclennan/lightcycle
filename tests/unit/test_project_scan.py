import os
import tempfile
import unittest

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.application.setup.project_scan import ScanProjectsUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


class _FakeGit:
    def __init__(self, git_repos=(), remotes=None):
        self._git_repos = set(git_repos)
        self._remotes = remotes or {}

    def is_repo_root(self, path):
        return path in self._git_repos

    def remote_url(self, path):
        return self._remotes.get(path)


class _Cfg:
    def __init__(self, data_root):
        self._data_root = data_root

    def data_root(self):
        return self._data_root


class TestScanProjects(unittest.TestCase):
    def test_no_repos_anywhere_returns_empty(self):
        root = "/tree"
        fs = FakeFs(dirs={root: ["a", "b"]})
        uc = ScanProjectsUseCase(FakeStore(), _FakeGit(), _Cfg("/nonexistent"), fs)
        self.assertEqual(uc.execute(root), [])

    def test_repo_with_ssh_remote_is_new(self):
        root = "/tree/x"
        git = _FakeGit(git_repos={root}, remotes={root: "git@github.com:acme/x.git"})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), FakeFs())
        [cand] = uc.execute(root)
        self.assertEqual(cand.identity, "acme/x")
        self.assertEqual(cand.shortcode, "X")
        self.assertEqual(cand.status, "new")

    def test_repo_with_https_remote_with_and_without_git_suffix(self):
        for remote in ("https://github.com/acme/x", "https://github.com/acme/x.git"):
            root = "/tree/x"
            git = _FakeGit(git_repos={root}, remotes={root: remote})
            uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), FakeFs())
            [cand] = uc.execute(root)
            self.assertEqual(cand.identity, "acme/x")

    def test_repo_with_no_origin_is_no_remote(self):
        root = "/tree/x"
        git = _FakeGit(git_repos={root})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), FakeFs())
        [cand] = uc.execute(root)
        self.assertEqual(cand.status, "no-remote")
        self.assertIsNone(cand.identity)
        self.assertIsNone(cand.remote)

    def test_repo_with_non_github_remote_is_no_remote_but_remote_preserved(self):
        root = "/tree/x"
        git = _FakeGit(git_repos={root}, remotes={root: "git@gitlab.com:acme/x.git"})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), FakeFs())
        [cand] = uc.execute(root)
        self.assertEqual(cand.status, "no-remote")
        self.assertIsNone(cand.identity)
        self.assertEqual(cand.remote, "git@gitlab.com:acme/x.git")

    def test_already_registered_shows_found_and_registered_separately(self):
        root = "/tree/x"
        store = FakeStore()
        store.add_project("acme/x", shortcode="OLD", local_path="/elsewhere")
        git = _FakeGit(git_repos={root}, remotes={root: "git@github.com:acme/x.git"})
        uc = ScanProjectsUseCase(store, git, _Cfg("/nonexistent"), FakeFs())
        [cand] = uc.execute(root)
        self.assertEqual(cand.status, "already-registered")
        self.assertEqual(cand.path, root)
        self.assertEqual(cand.registered_path, "/elsewhere")
        self.assertEqual(cand.registered_shortcode, "OLD")

    def test_prunes_at_a_repo_boundary(self):
        root = "/tree"
        sub = os.path.join(root, "sub")
        fs = FakeFs(dirs={root: ["sub"]})
        git = _FakeGit(git_repos={root, sub})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), fs)
        candidates = uc.execute(root)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].path, root)

    def test_hidden_directory_is_never_descended_into(self):
        root = "/tree"
        hidden = os.path.join(root, ".hidden")
        nested = os.path.join(hidden, "repo")
        fs = FakeFs(dirs={root: [".hidden"], hidden: ["repo"]})
        git = _FakeGit(git_repos={nested})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), fs)
        self.assertEqual(uc.execute(root), [])

    def test_node_modules_is_skipped_the_same_way(self):
        root = "/tree"
        nm = os.path.join(root, "node_modules")
        nested = os.path.join(nm, "repo")
        fs = FakeFs(dirs={root: ["node_modules"], nm: ["repo"]})
        git = _FakeGit(git_repos={nested})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg("/nonexistent"), fs)
        self.assertEqual(uc.execute(root), [])

    def test_configured_data_home_is_skipped_even_mid_tree(self):
        root = "/tree"
        state = os.path.join(root, "state")
        app = os.path.join(root, "app")
        nested = os.path.join(state, "repo")
        fs = FakeFs(dirs={root: ["state", "app"], app: []})
        git = _FakeGit(git_repos={nested})
        uc = ScanProjectsUseCase(FakeStore(), git, _Cfg(state), fs)
        self.assertEqual(uc.execute(root), [])

    def test_multiple_nested_candidates_mixed_statuses(self):
        root = "/tree"
        new_repo = os.path.join(root, "new")
        reg_repo = os.path.join(root, "registered")
        noremote_repo = os.path.join(root, "noremote")
        fs = FakeFs(dirs={root: ["new", "registered", "noremote"]})
        store = FakeStore()
        store.add_project("acme/registered", shortcode="REG", local_path="/elsewhere")
        git = _FakeGit(
            git_repos={new_repo, reg_repo, noremote_repo},
            remotes={
                new_repo: "git@github.com:acme/new.git",
                reg_repo: "git@github.com:acme/registered.git",
            },
        )
        uc = ScanProjectsUseCase(store, git, _Cfg("/nonexistent"), fs)
        candidates = uc.execute(root)
        by_path = {c.path: c for c in candidates}
        self.assertEqual(len(candidates), 3)
        self.assertEqual(by_path[new_repo].status, "new")
        self.assertEqual(by_path[reg_repo].status, "already-registered")
        self.assertEqual(by_path[noremote_repo].status, "no-remote")

    def test_symlink_cycle_terminates_instead_of_recursing_forever(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "dir"))
        os.symlink(root, os.path.join(root, "dir", "loop"))
        git = _FakeGit()
        config = _Cfg("/nonexistent")
        fs = FsAdapter(config)
        uc = ScanProjectsUseCase(FakeStore(), git, config, fs)
        self.assertEqual(uc.execute(root), [])
