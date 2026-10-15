import unittest

from lightcycle.application.workflows.engine_requirement_check import installed_bundle_conflicts
from lightcycle.ports.workflow_source import OriginRegistration


class FakeSource:
    def __init__(self):
        self.registries = {}
        self.manifests = {}

    def add(self, origin, sha, manifest, on_disk=True, registered=True):
        if registered:
            self.registries[origin] = OriginRegistration(url=origin, ref="", current=sha)
        if on_disk:
            self.manifests[(origin, sha)] = manifest

    def list_origins(self):
        return sorted(set(self.registries) | {o for o, _ in self.manifests})

    def read_registry(self, origin):
        return self.registries.get(origin)

    def has_version(self, origin, sha):
        return (origin, sha) in self.manifests

    def pinned_bundle(self, origin, sha):
        return (origin, sha)

    def read_manifest(self, bundle):
        return self.manifests[bundle]


class TestInstalledBundleConflicts(unittest.TestCase):
    def test_only_excluding_and_malformed_origins_appear(self):
        source = FakeSource()
        source.add("excludes", "sha-a", 'contract = 1\nrequires-engine = "<0.7.0"\n')
        source.add("accepts", "sha-b", 'contract = 1\nrequires-engine = ">=0.6.0"\n')
        source.add("silent", "sha-c", "contract = 1\n")
        source.add("gone", "sha-d", "contract = 1\n", on_disk=False)
        source.add("broken", "sha-e", 'contract = 1\nrequires-engine = ">=0.6"\n')
        source.add("unregistered", "sha-f", 'contract = 1\nrequires-engine = ">=9.0.0"\n', registered=False)
        messages = installed_bundle_conflicts(source, "0.7.0")
        self.assertEqual(len(messages), 2)
        excluding = next(m for m in messages if "excludes" in m.split()[1])
        self.assertIn("sha-a", excluding)
        self.assertIn("<0.7.0", excluding)
        self.assertIn("0.7.0", excluding)
        malformed = next(m for m in messages if m.startswith("origin broken"))
        self.assertIn("sha-e", malformed)
        self.assertIn("requires-engine", malformed)


if __name__ == "__main__":
    unittest.main()
