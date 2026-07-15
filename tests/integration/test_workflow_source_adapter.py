import os
import subprocess
import tempfile
import unittest

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.errors import WorkflowSourceError
from lightcycle.application.workflows.upgrade import UpgradeWorkflowSourceUseCase


class FakeConfig:
    def __init__(self, data_root):
        self._data_root = data_root

    def data_root(self):
        return self._data_root


def _git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True, text=True)


def _make_source_repo():
    repo = tempfile.mkdtemp()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    with open(os.path.join(repo, "source.toml"), "w") as f:
        f.write('name = "acme"\ncontract = 1\ndescription = "acme flows"\n')
    os.makedirs(os.path.join(repo, "workflows"))
    os.makedirs(os.path.join(repo, "steps"))
    with open(os.path.join(repo, "workflows", "build.md"), "w") as f:
        f.write("entry: code\n")
    with open(os.path.join(repo, "steps", "code.md"), "w") as f:
        f.write("---\nmodel: x\n---\nbody\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    head = subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    return repo, head


def _adapter():
    return WorkflowSourceAdapter(FakeConfig(tempfile.mkdtemp()))


class TestFetch(unittest.TestCase):
    def test_fetch_resolves_the_ref_to_a_sha_and_checks_out_the_manifest(self):
        repo, head = _make_source_repo()
        adapter = _adapter()
        checkout, sha = adapter.fetch(repo, "main")
        self.assertEqual(sha, head)
        self.assertEqual(adapter.read_manifest(checkout),
                         'name = "acme"\ncontract = 1\ndescription = "acme flows"\n')
        adapter.cleanup(checkout)


class TestMaterialize(unittest.TestCase):
    def test_materialize_copies_the_bundle_and_is_idempotent(self):
        repo, head = _make_source_repo()
        adapter = _adapter()
        checkout, sha = adapter.fetch(repo, "main")
        bundle = adapter.materialize("acme", sha, checkout)
        self.assertTrue(os.path.exists(os.path.join(bundle, "source.toml")))
        self.assertTrue(os.path.exists(os.path.join(bundle, "workflows", "build.md")))
        self.assertTrue(os.path.exists(os.path.join(bundle, "steps", "code.md")))
        self.assertTrue(adapter.has_version("acme", sha))
        adapter.materialize("acme", sha, checkout)
        self.assertTrue(adapter.has_version("acme", sha))
        adapter.cleanup(checkout)


class TestBundleResolution(unittest.TestCase):
    def test_bundle_path_and_current_sha(self):
        repo, head = _make_source_repo()
        adapter = _adapter()
        checkout, sha = adapter.fetch(repo, "main")
        adapter.materialize("acme", sha, checkout)
        adapter.write_registry("acme", repo, "main", sha)
        self.assertEqual(adapter.bundle_path("acme", sha),
                         os.path.join(adapter._root(), "acme", sha))
        self.assertTrue(os.path.isdir(adapter.bundle_path("acme", sha)))
        self.assertEqual(adapter.current_sha("acme"), sha)
        adapter.cleanup(checkout)

    def test_current_sha_missing_origin_is_none(self):
        self.assertIsNone(_adapter().current_sha("nope"))


class TestRegistry(unittest.TestCase):
    def test_write_then_read_roundtrips(self):
        adapter = _adapter()
        adapter.write_registry("acme", "github.com/acme/f", "main", "abc123")
        self.assertEqual(
            adapter.read_registry("acme"),
            {"url": "github.com/acme/f", "ref": "main", "current": "abc123"},
        )

    def test_read_missing_registry_is_none(self):
        self.assertIsNone(_adapter().read_registry("nope"))


class TestListingAndRemoval(unittest.TestCase):
    def test_list_origins_and_versions_then_remove(self):
        repo, head = _make_source_repo()
        adapter = _adapter()
        checkout, sha = adapter.fetch(repo, "main")
        adapter.materialize("acme", sha, checkout)
        adapter.write_registry("acme", repo, "main", sha)
        self.assertEqual(adapter.list_origins(), ["acme"])
        self.assertEqual(adapter.list_versions("acme"), [sha])
        adapter.remove_version("acme", sha)
        self.assertEqual(adapter.list_versions("acme"), [])
        adapter.remove_origin("acme")
        self.assertEqual(adapter.list_origins(), [])
        adapter.cleanup(checkout)


class _Store:
    def all_nodes(self):
        return []


class _Config:
    def workflow_retention(self):
        return 5


def _make_source_repo_with_unresolved_step():
    repo = tempfile.mkdtemp()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    with open(os.path.join(repo, "source.toml"), "w") as f:
        f.write('name = "acme"\ncontract = 1\ndescription = "acme flows"\n')
    os.makedirs(os.path.join(repo, "workflows"))
    os.makedirs(os.path.join(repo, "steps"))
    with open(os.path.join(repo, "workflows", "build.md"), "w") as f:
        f.write("entry: missing-step\n")
    with open(os.path.join(repo, "steps", "code.md"), "w") as f:
        f.write("---\nmodel: x\n---\nbody\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


class TestBundleReferenceValidation(unittest.TestCase):
    def test_add_refuses_unresolved_step_reference_against_real_checkout(self):
        repo = _make_source_repo_with_unresolved_step()
        source = _adapter()
        fs = FsAdapter(None)
        with self.assertRaises(WorkflowSourceError):
            AddWorkflowSourceUseCase(source, _Store(), _Config(), fs).execute(
                url=repo, ref="main", name=None)
        self.assertIsNone(source.read_registry("acme"))
        self.assertEqual(source.list_versions("acme"), [])

    def test_upgrade_refuses_unresolved_step_reference_against_real_checkout(self):
        repo, head = _make_source_repo()
        source = _adapter()
        fs = FsAdapter(None)
        AddWorkflowSourceUseCase(source, _Store(), _Config(), fs).execute(
            url=repo, ref="main", name="acme")
        with open(os.path.join(repo, "workflows", "build.md"), "w") as f:
            f.write("entry: missing-step\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "break entry")
        with self.assertRaises(WorkflowSourceError):
            UpgradeWorkflowSourceUseCase(source, _Store(), _Config(), fs).execute("acme")
        self.assertEqual(source.current_sha("acme"), head)


if __name__ == "__main__":
    unittest.main()
