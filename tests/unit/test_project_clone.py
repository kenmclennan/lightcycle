import os
import shutil
import subprocess
import tempfile
import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.project_clone import ensure_project_cloned
from tests.support.fake_store import FakeStore


class _Cfg:
    def __init__(self, projects_root):
        self._projects_root = projects_root

    def projects_root(self):
        return self._projects_root


class _FakeGit:
    def __init__(self, clone_result=True, git_repos=()):
        self.calls = []
        self._clone_result = clone_result
        self._git_repos = set(git_repos)

    def clone_identity(self, identity, dest):
        self.calls.append(("clone_identity", identity, dest))
        if self._clone_result:
            os.makedirs(dest, exist_ok=True)
        return self._clone_result

    def is_git_repo(self, path):
        self.calls.append(("is_git_repo", path))
        return path in self._git_repos


def _real_repo():
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", d], check=True)
    return d


class TestEnsureProjectCloned(unittest.TestCase):
    def test_no_ref_is_a_no_op(self):
        s = FakeStore()
        git = _FakeGit()
        ensure_project_cloned(s, git, _Cfg(tempfile.mkdtemp()), None)
        self.assertEqual(git.calls, [])

    def test_absolute_path_ref_is_a_no_op(self):
        s = FakeStore()
        git = _FakeGit()
        ensure_project_cloned(s, git, _Cfg(tempfile.mkdtemp()), "/elsewhere/app")
        self.assertEqual(git.calls, [])

    def test_unregistered_ref_raises_use_case_error(self):
        s = FakeStore()
        git = _FakeGit()
        with self.assertRaises(UseCaseError):
            ensure_project_cloned(s, git, _Cfg(tempfile.mkdtemp()), "ghost")

    def test_ambiguous_ref_raises_use_case_error(self):
        s = FakeStore()
        s.add_project("acme/app", local_path=_real_repo())
        s.add_project("other/app", local_path=_real_repo())
        git = _FakeGit()
        with self.assertRaises(UseCaseError):
            ensure_project_cloned(s, git, _Cfg(tempfile.mkdtemp()), "app")

    def test_already_has_a_real_local_checkout_is_a_no_op(self):
        s = FakeStore()
        local = tempfile.mkdtemp()
        s.add_project("acme/horde", local_path=local)
        git = _FakeGit()
        ensure_project_cloned(s, git, _Cfg(tempfile.mkdtemp()), "horde")
        self.assertEqual(git.calls, [])

    def test_local_path_set_but_directory_gone_raises_use_case_error(self):
        s = FakeStore()
        local = tempfile.mkdtemp()
        shutil.rmtree(local)
        s.add_project("acme/horde", local_path=local)
        git = _FakeGit()
        with self.assertRaises(UseCaseError) as ctx:
            ensure_project_cloned(s, git, _Cfg(tempfile.mkdtemp()), "horde")
        self.assertIn(local, str(ctx.exception))

    def test_null_local_path_and_no_destination_clones_and_records_the_path(self):
        s = FakeStore()
        s.add_project("acme/horde", shortcode="HORDE")
        projects_root = tempfile.mkdtemp()
        git = _FakeGit(clone_result=True)

        ensure_project_cloned(s, git, _Cfg(projects_root), "horde")

        expected = os.path.join(projects_root, "acme", "horde")
        self.assertEqual(git.calls, [("clone_identity", "acme/horde", expected)])
        self.assertEqual(s.get_project("acme/horde").local_path, expected)

    def test_null_local_path_and_clone_failure_raises_and_leaves_local_path_none(self):
        s = FakeStore()
        s.add_project("acme/horde", shortcode="HORDE")
        projects_root = tempfile.mkdtemp()
        git = _FakeGit(clone_result=False)

        with self.assertRaises(UseCaseError) as ctx:
            ensure_project_cloned(s, git, _Cfg(projects_root), "horde")

        self.assertIn("acme/horde", str(ctx.exception))
        self.assertIsNone(s.get_project("acme/horde").local_path)

    def test_null_local_path_and_destination_already_a_git_repo_is_adopted(self):
        s = FakeStore()
        s.add_project("acme/horde", shortcode="HORDE")
        projects_root = tempfile.mkdtemp()
        dest = os.path.join(projects_root, "acme", "horde")
        os.makedirs(dest)
        git = _FakeGit(git_repos={dest})

        ensure_project_cloned(s, git, _Cfg(projects_root), "horde")

        self.assertEqual(git.calls, [("is_git_repo", dest)])
        self.assertEqual(s.get_project("acme/horde").local_path, dest)

    def test_null_local_path_and_destination_exists_but_is_not_a_git_repo_raises(self):
        s = FakeStore()
        s.add_project("acme/horde", shortcode="HORDE")
        projects_root = tempfile.mkdtemp()
        dest = os.path.join(projects_root, "acme", "horde")
        os.makedirs(dest)
        (open(os.path.join(dest, "keepme.txt"), "w")).close()
        git = _FakeGit(git_repos=())

        with self.assertRaises(UseCaseError) as ctx:
            ensure_project_cloned(s, git, _Cfg(projects_root), "horde")

        self.assertIn(dest, str(ctx.exception))
        self.assertTrue(os.path.isfile(os.path.join(dest, "keepme.txt")))
        self.assertIsNone(s.get_project("acme/horde").local_path)


if __name__ == "__main__":
    unittest.main()
