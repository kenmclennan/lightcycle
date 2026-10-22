from lightcycle.application.inspect import DoctorUseCase
from tests.support.fake_github_budget import FakeGithubBudget
import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr

from lightcycle import cli
from lightcycle.config import ResolvedSetting
from lightcycle.ports.workflow_source import OriginRegistration
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_machine import FakeMachine
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeConfigReloadStatus, FakeGuidanceSyncStatus, FakeLock


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

    def pinned_bundle(self, origin, sha):
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
        self.registries[name] = OriginRegistration(url=url or name, ref=ref, current=None)

    def fail_resolve(self, name, reason):
        self.failures[self.registries[name].url] = reason

    def unresolvable_reason(self, url, ref):
        return self.failures.get(url)


class FakeConfig:
    def version(self):
        return "0.6.319"

    def missing_config_keys(self):
        return ()

    def obsolete_config_keys(self):
        return ()

    def resolved_settings(self):
        return ()

    def default_origin(self):
        return "acme"

    def schedule_blocks(self):
        return {}


class FakeWorkflowBundle:
    def step_roles(self, root):
        return []

    def parse_step(self, role, root):
        return None

    def workflow_text(self, name, root):
        return None


class FakeWorktrees:
    def worktree_path(self, item):
        raise AssertionError("no claimed steps expected in cmd_doctor tests")


class FakeContainer:
    def __init__(self, store, workflow_source=None, config=None, workflow_bundle=None):
        self.store = store
        self.workflow_source = workflow_source or FakeWorkflowSource()
        self.config = config or FakeConfig()
        self.workflow_bundle = workflow_bundle or FakeWorkflowBundle()
        self.fs = FakeFs()
        self.machine = FakeMachine()
        self.git = FakeGit()
        self.guidance_sync_status = FakeGuidanceSyncStatus()
        self.config_reload_status = FakeConfigReloadStatus()
        self.lock = FakeLock(running=False)

    def github_budget(self):
        return FakeGithubBudget()

    def worktrees(self):
        return FakeWorktrees()

    def doctor(self):
        return DoctorUseCase(
            self.store, self.workflow_source, self.config, self.workflow_bundle,
            self.fs, self.machine, self.worktrees(),
            self.git, self.guidance_sync_status,
            self.config_reload_status, self.lock, self.github_budget(),
        )


class TestCmdDoctor(unittest.TestCase):
    def test_healthy_store_returns_zero_and_prints_ok(self):
        cli.set_container(FakeContainer(FakeStore()))
        rc, out, err = call(cli.cmd_doctor)
        self.assertEqual(rc, 0)
        self.assertIn("healthy", out)
        for cat in ("store", "pins", "contract", "origin", "config", "orphans"):
            self.assertIn("%s: ok" % cat, out)

    def test_unhealthy_store_returns_one(self):
        store = FakeStore()
        store.create_step(item="missing-parent")
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
        self.assertEqual(
            set(data.keys()), {"store", "pins", "contract", "origin", "config", "orphans", "facets", "guidance", "github"}
        )
        for probs in data.values():
            self.assertEqual(probs, [])

    def test_the_text_output_prints_the_github_line_with_the_figures(self):
        container = FakeContainer(FakeStore())
        container.github_budget = lambda: FakeGithubBudget(
            remaining=4261, limit=5000, reset=1792503970)
        cli.set_container(container)

        rc, out, err = call(cli.cmd_doctor)

        self.assertEqual(rc, 0)
        self.assertRegex(out, r"github: ok - 4261/5000 remaining, resets at \d\d:\d\d:\d\d")

    def test_open_item_with_a_teardown_refusal_is_listed_under_orphans(self):
        store = FakeStore()
        item = store.create_item("stuck", "a description")
        store.add_artifact(item, "teardown-refused", "worktree /w has uncommitted paths: a.py", internal=True)
        cli.set_container(FakeContainer(store))

        rc, out, err = call(cli.cmd_doctor, "--json")

        data = json.loads(out)
        self.assertEqual(rc, 1)
        self.assertEqual(len(data["orphans"]), 1)
        self.assertIn(item, data["orphans"][0]["message"])
        self.assertIn("a.py", data["orphans"][0]["message"])
        self.assertIn("close the item again", data["orphans"][0]["fix"])

    def test_closed_item_with_a_teardown_refusal_artifact_is_not_listed(self):
        store = FakeStore()
        item = store.create_item("done now", "a description")
        store.add_artifact(item, "teardown-refused", "worktree /w has uncommitted paths: a.py", internal=True)
        store.complete_node(item, "closed", "completed")
        cli.set_container(FakeContainer(store))

        rc, out, err = call(cli.cmd_doctor, "--json")

        self.assertEqual(json.loads(out)["orphans"], [])

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

    def test_rejected_config_value_reports_rejected_not_blank(self):
        class RejectedFakeConfig(FakeConfig):
            def resolved_settings(self):
                return (
                    ResolvedSetting(
                        key="max-agents", value=None,
                        error="config value 'max-agents' must be >= 0 (got -1)",
                        state="invalid", env_var=None, seed="5",
                    ),
                )

        cli.set_container(FakeContainer(FakeStore(), config=RejectedFakeConfig()))
        rc, out, err = call(cli.cmd_doctor)
        self.assertEqual(rc, 1)
        self.assertIn("config:", out)
        self.assertIn("max-agents", out)
        self.assertIn("rejected", out)
        self.assertIn("-1", out)
        self.assertNotIn("set but blank", out)

        cli.set_container(FakeContainer(FakeStore(), config=RejectedFakeConfig()))
        rc, out, err = call(cli.cmd_doctor, "--json")
        self.assertEqual(rc, 1)
        data = json.loads(out)
        self.assertTrue(any("max-agents" in p["message"] and "-1" in p["message"]
                             for p in data["config"]))

    def _blank_container(self):
        class BlankFakeConfig(FakeConfig):
            def resolved_settings(self):
                return (
                    ResolvedSetting(
                        key="trusted-authors", value=None, error=None,
                        state="unset", env_var=None, seed="",
                    ),
                )

        return FakeContainer(FakeStore(), config=BlankFakeConfig())

    def test_json_blank_key_carries_kind_and_fix(self):
        cli.set_container(self._blank_container())
        rc, out, err = call(cli.cmd_doctor, "--json")
        self.assertEqual(rc, 1)
        (finding,) = json.loads(out)["config"]
        self.assertEqual(finding["kind"], "config-key-blank")
        self.assertIn("trusted-authors", finding["fix"])

    def test_json_finding_without_a_fix_omits_kind_and_fix(self):
        class ObsoleteFakeConfig(FakeConfig):
            def missing_config_keys(self):
                return ("max-agents",)

        cli.set_container(FakeContainer(FakeStore(), config=ObsoleteFakeConfig()))
        rc, out, err = call(cli.cmd_doctor, "--json")
        (finding,) = json.loads(out)["config"]
        self.assertNotIn("kind", finding)
        self.assertNotIn("fix", finding)

    def test_text_blank_key_prints_the_fix_beneath_the_message(self):
        cli.set_container(self._blank_container())
        rc, out, err = call(cli.cmd_doctor)
        lines = out.splitlines()
        at = next(i for i, ln in enumerate(lines) if "set but blank" in ln)
        self.assertTrue(lines[at + 1].startswith("    fix: "))

    def test_json_unhealthy_shape_and_exit_code(self):
        store = FakeStore()
        item = store.create_step(item="missing-parent")
        cli.set_container(FakeContainer(store))
        rc, out, err = call(cli.cmd_doctor, "--json")
        self.assertEqual(rc, 1)
        data = json.loads(out)
        self.assertEqual(len(data["store"]), 1)
        self.assertEqual(data["store"][0]["node_id"], item)


if __name__ == "__main__":
    unittest.main()
