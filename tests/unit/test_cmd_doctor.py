import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr

from lightcycle import cli
from tests.support.fake_store import FakeStore


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class FakeWorkflowSource:
    def __init__(self):
        self.registries = {}
        self.failures = {}

    def has_version(self, origin, sha):
        return True

    def bundle_path(self, origin, sha):
        return (origin, sha)

    def read_manifest(self, bundle):
        return 'contract = 1\n'

    def current_sha(self, origin):
        return "sha1"

    def list_origins(self):
        return sorted(self.registries)

    def read_registry(self, name):
        return self.registries.get(name)

    def register_origin(self, name, url=None, ref=""):
        self.registries[name] = {"url": url or name, "ref": ref}

    def fail_resolve(self, name, reason):
        self.failures[self.registries[name]["url"]] = reason

    def unresolvable_reason(self, url, ref):
        return self.failures.get(url)


class FakeConfig:
    def missing_config_keys(self):
        return ()

    def obsolete_config_keys(self):
        return ()

    def default_origin(self):
        return "acme"


class FakeContainer:
    def __init__(self, store, workflow_source=None, config=None):
        self.store = store
        self.workflow_source = workflow_source or FakeWorkflowSource()
        self.config = config or FakeConfig()


class TestCmdDoctor(unittest.TestCase):
    def test_healthy_store_returns_zero_and_prints_ok(self):
        cli.set_container(FakeContainer(FakeStore()))
        rc, out, err = call(cli.cmd_doctor)
        self.assertEqual(rc, 0)
        self.assertIn("healthy", out)
        for cat in ("store", "pins", "contract", "origin", "config"):
            self.assertIn("%s: ok" % cat, out)

    def test_unhealthy_store_returns_one(self):
        store = FakeStore()
        item = store.create_step("a step", parent="missing-parent")
        cli.set_container(FakeContainer(store))
        rc, out, err = call(cli.cmd_doctor)
        self.assertEqual(rc, 1)
        self.assertIn("unhealthy", out)
        self.assertIn("store:", out)

    def test_json_healthy_shape_and_exit_code(self):
        cli.set_container(FakeContainer(FakeStore()))
        rc, out, err = call(cli.cmd_doctor, "--json")
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(set(data.keys()), {"store", "pins", "contract", "origin", "config"})
        for probs in data.values():
            self.assertEqual(probs, [])

    def test_failing_origin_reports_in_origin_category(self):
        source = FakeWorkflowSource()
        source.register_origin("acme2", ref="gone-branch")
        source.fail_resolve("acme2", "ref 'gone-branch' no longer resolves against acme2")
        cli.set_container(FakeContainer(FakeStore(), workflow_source=source))
        rc, out, err = call(cli.cmd_doctor)
        self.assertEqual(rc, 1)
        self.assertIn("origin:", out)
        self.assertIn("acme2", out)

        cli.set_container(FakeContainer(FakeStore(), workflow_source=source))
        rc, out, err = call(cli.cmd_doctor, "--json")
        self.assertEqual(rc, 1)
        data = json.loads(out)
        self.assertTrue(any("acme2" in p["message"] for p in data["origin"]))

    def test_obsolete_config_key_reports_in_config_category(self):
        class ObsoleteFakeConfig(FakeConfig):
            def obsolete_config_keys(self):
                return ("old-key",)

        cli.set_container(FakeContainer(FakeStore(), config=ObsoleteFakeConfig()))
        rc, out, err = call(cli.cmd_doctor)
        self.assertEqual(rc, 1)
        self.assertIn("config:", out)
        self.assertIn("old-key", out)

        cli.set_container(FakeContainer(FakeStore(), config=ObsoleteFakeConfig()))
        rc, out, err = call(cli.cmd_doctor, "--json")
        self.assertEqual(rc, 1)
        data = json.loads(out)
        self.assertTrue(any("old-key" in p["message"] for p in data["config"]))

    def test_json_unhealthy_shape_and_exit_code(self):
        store = FakeStore()
        item = store.create_step("a step", parent="missing-parent")
        cli.set_container(FakeContainer(store))
        rc, out, err = call(cli.cmd_doctor, "--json")
        self.assertEqual(rc, 1)
        data = json.loads(out)
        self.assertEqual(len(data["store"]), 1)
        self.assertEqual(data["store"][0]["node_id"], item)


if __name__ == "__main__":
    unittest.main()
