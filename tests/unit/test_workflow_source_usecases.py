import unittest

from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.errors import WorkflowSourceError
from lightcycle.application.workflows.list import ListWorkflowSourcesUseCase
from lightcycle.application.workflows.remove import RemoveWorkflowSourceUseCase
from lightcycle.application.workflows.upgrade import UpgradeWorkflowSourceUseCase


class FakeSource:
    def __init__(self):
        self.remotes = {}
        self.materialized = {}
        self.registries = {}
        self._checkouts = {}
        self.cleaned = []
        self._n = 0

    def add_remote(self, url, manifest, sha):
        self.remotes[url] = (manifest, sha)

    def fetch(self, url, ref):
        manifest, sha = self.remotes[url]
        self._n += 1
        checkout = "checkout-%d" % self._n
        self._checkouts[checkout] = manifest
        return checkout, sha

    def read_manifest(self, checkout_dir):
        return self._checkouts[checkout_dir]

    def materialize(self, origin, sha, checkout_dir):
        self.materialized.setdefault(origin, [])
        if sha not in self.materialized[origin]:
            self.materialized[origin].append(sha)
        return "%s/%s" % (origin, sha)

    def has_version(self, origin, sha):
        return sha in self.materialized.get(origin, [])

    def write_registry(self, origin, url, ref, current):
        self.registries[origin] = {"url": url, "ref": ref, "current": current}

    def read_registry(self, origin):
        return self.registries.get(origin)

    def list_origins(self):
        return sorted(self.registries)

    def list_versions(self, origin):
        return list(reversed(self.materialized.get(origin, [])))

    def remove_version(self, origin, sha):
        self.materialized[origin] = [s for s in self.materialized.get(origin, []) if s != sha]

    def remove_origin(self, origin):
        self.materialized.pop(origin, None)
        self.registries.pop(origin, None)

    def cleanup(self, checkout_dir):
        self.cleaned.append(checkout_dir)


class _Node:
    def __init__(self, workflow):
        self.workflow = workflow


class FakeStore:
    def __init__(self, nodes=None):
        self._nodes = nodes or []

    def all_nodes(self):
        return list(self._nodes)


class FakeConfig:
    def __init__(self, retention=3):
        self._retention = retention

    def workflow_retention(self):
        return self._retention


def _add(source, store=None, config=None):
    return AddWorkflowSourceUseCase(source, store or FakeStore(), config or FakeConfig())


class TestAdd(unittest.TestCase):
    def test_add_registers_and_materializes(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        resp = _add(source).execute(url="u", ref="main", name=None)
        self.assertEqual(resp.origin, "acme")
        self.assertEqual(resp.sha, "sha1")
        self.assertTrue(source.has_version("acme", "sha1"))
        self.assertEqual(source.read_registry("acme"),
                         {"url": "u", "ref": "main", "current": "sha1"})
        self.assertEqual(source.cleaned, ["checkout-1"])

    def test_name_flag_overrides_manifest_name(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        resp = _add(source).execute(url="u", ref="main", name="mine")
        self.assertEqual(resp.origin, "mine")

    def test_missing_origin_name_raises(self):
        source = FakeSource()
        source.add_remote("u", "contract = 1\n", "sha1")
        with self.assertRaises(WorkflowSourceError):
            _add(source).execute(url="u", ref="main", name=None)

    def test_incompatible_contract_raises_and_registers_nothing(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 99\n', "sha1")
        with self.assertRaises(WorkflowSourceError):
            _add(source).execute(url="u", ref="main", name=None)
        self.assertEqual(source.list_origins(), [])
        self.assertEqual(source.cleaned, ["checkout-1"])

    def test_add_existing_origin_raises(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        with self.assertRaises(WorkflowSourceError):
            _add(source).execute(url="u", ref="main", name=None)


class TestUpgrade(unittest.TestCase):
    def test_upgrade_pulls_new_sha_and_reports_changed(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        resp = UpgradeWorkflowSourceUseCase(source, FakeStore(), FakeConfig()).execute("acme")
        self.assertEqual(resp.sha, "sha2")
        self.assertTrue(resp.changed)
        self.assertEqual(source.read_registry("acme")["current"], "sha2")

    def test_upgrade_unregistered_origin_raises(self):
        with self.assertRaises(WorkflowSourceError):
            UpgradeWorkflowSourceUseCase(FakeSource(), FakeStore(), FakeConfig()).execute("nope")

    def test_upgrade_prunes_beyond_retention_but_keeps_pinned(self):
        source = FakeSource()
        store = FakeStore([_Node("acme/build@sha1")])
        cfg = FakeConfig(retention=1)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        AddWorkflowSourceUseCase(source, store, cfg).execute(url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        UpgradeWorkflowSourceUseCase(source, store, cfg).execute("acme")
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha3")
        UpgradeWorkflowSourceUseCase(source, store, cfg).execute("acme")
        self.assertEqual(set(source.materialized["acme"]), {"sha1", "sha3"})


class TestRemove(unittest.TestCase):
    def test_remove_refuses_when_a_live_item_pins_a_version(self):
        source = FakeSource()
        store = FakeStore([_Node("acme/build@sha1")])
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        AddWorkflowSourceUseCase(source, store, FakeConfig()).execute(url="u", ref="main", name=None)
        with self.assertRaises(WorkflowSourceError):
            RemoveWorkflowSourceUseCase(source, store).execute("acme")
        self.assertEqual(source.list_origins(), ["acme"])

    def test_remove_deregisters_when_unpinned(self):
        source = FakeSource()
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        _add(source).execute(url="u", ref="main", name=None)
        RemoveWorkflowSourceUseCase(source, FakeStore()).execute("acme")
        self.assertEqual(source.list_origins(), [])

    def test_remove_unregistered_raises(self):
        with self.assertRaises(WorkflowSourceError):
            RemoveWorkflowSourceUseCase(FakeSource(), FakeStore()).execute("nope")


class TestList(unittest.TestCase):
    def test_list_reports_origins_versions_and_pins(self):
        source = FakeSource()
        store = FakeStore([_Node("acme/build@sha1")])
        cfg = FakeConfig(retention=5)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha1")
        AddWorkflowSourceUseCase(source, store, cfg).execute(url="u", ref="main", name=None)
        source.add_remote("u", 'name = "acme"\ncontract = 1\n', "sha2")
        UpgradeWorkflowSourceUseCase(source, store, cfg).execute("acme")
        resp = ListWorkflowSourcesUseCase(source, store).execute()
        self.assertEqual(len(resp.origins), 1)
        view = resp.origins[0]
        self.assertEqual(view.name, "acme")
        self.assertEqual(view.current, "sha2")
        self.assertEqual(view.url, "u")
        self.assertEqual(set(view.pinned), {"sha1"})
        self.assertEqual(set(view.versions), {"sha1", "sha2"})


if __name__ == "__main__":
    unittest.main()
