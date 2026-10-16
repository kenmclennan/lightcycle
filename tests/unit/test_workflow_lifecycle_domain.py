import os
import unittest

from lightcycle.domain.workflows.lifecycle import (
    lifecycle_problems,
    missing_required_keys,
    parse_lifecycle,
    workflow_script_env,
)
from lightcycle.frontmatter import split_frontmatter

BINDING = """---
lifecycle:
  install: scripts/install.sh
  upgrade: scripts/upgrade.sh
  maintain: scripts/maintain.sh
  cron: 0 3 * * *
config:
  api-token: required
  region: optional
config-example:
  api-token: example-token
---
body
"""


def _parse(text):
    meta, _ = split_frontmatter(text)
    return parse_lifecycle(meta)


def _problems(lifecycle, present=None, executable=None):
    present = present if present is not None else {
        "scripts/install.sh", "scripts/upgrade.sh", "scripts/maintain.sh"}
    executable = executable if executable is not None else set(present)
    return lifecycle_problems(lifecycle, lambda p: p in present, lambda p: p in executable)


def _with(**changes):
    base = {
        "install": "scripts/install.sh", "upgrade": "scripts/upgrade.sh",
        "maintain": "scripts/maintain.sh", "cron": "0 3 * * *",
    }
    base.update(changes)
    lines = ["---", "lifecycle:"] + ["  %s: %s" % (k, v) for k, v in base.items() if v is not None]
    lines += ["config:", "  api-token: required", "config-example:", "  api-token: x", "---"]
    return _parse("\n".join(lines))


class TestParse(unittest.TestCase):
    def test_the_binding_block_parses_to_hooks_cron_and_keys(self):
        lifecycle = _parse(BINDING)
        self.assertEqual(lifecycle.install, "scripts/install.sh")
        self.assertEqual(lifecycle.upgrade, "scripts/upgrade.sh")
        self.assertEqual(lifecycle.maintain, "scripts/maintain.sh")
        self.assertEqual(lifecycle.cron, "0 3 * * *")
        self.assertEqual(lifecycle.config, (("api-token", True), ("region", False)))
        self.assertEqual(lifecycle.examples, {"api-token": "example-token"})

    def test_a_workflow_with_no_block_has_no_lifecycle(self):
        self.assertIsNone(_parse("---\nsummary: x\n---\nbody\n"))

    def test_a_malformed_block_raises(self):
        with self.assertRaises(ValueError):
            _parse("---\nlifecycle: nope\n---\n")
        with self.assertRaises(ValueError):
            _parse("---\nlifecycle:\n  bogus: scripts/x.sh\n---\n")
        with self.assertRaises(ValueError):
            _parse("---\nlifecycle:\n  install: scripts/x.sh\nconfig:\n  a: maybe\n---\n")

    def test_the_committed_library_workflow_has_no_lifecycle(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "support", "library", "workflows", "spec-driven.md")
        with open(path) as f:
            lifecycle = _parse(f.read())
        self.assertIsNone(lifecycle)


class TestProblems(unittest.TestCase):
    def test_the_binding_block_is_clean(self):
        self.assertEqual(_problems(_parse(BINDING)), [])

    def test_a_path_outside_scripts_is_a_problem(self):
        found = _problems(_with(install="bin/install.sh"))
        self.assertEqual(len(found), 1)
        self.assertIn("under scripts/", found[0])

    def test_a_dotdot_segment_is_a_problem(self):
        found = _problems(_with(install="scripts/../install.sh"))
        self.assertEqual(len(found), 1)
        self.assertIn("..", found[0])

    def test_a_missing_script_is_a_problem(self):
        found = _problems(_parse(BINDING), present={"scripts/install.sh", "scripts/maintain.sh"})
        self.assertEqual(len(found), 1)
        self.assertIn("scripts/upgrade.sh does not exist", found[0])

    def test_a_non_executable_script_is_a_problem(self):
        found = _problems(_parse(BINDING), executable={"scripts/install.sh", "scripts/upgrade.sh"})
        self.assertEqual(len(found), 1)
        self.assertIn("scripts/maintain.sh is not executable", found[0])

    def test_maintain_without_cron_is_a_problem(self):
        found = _problems(_with(cron=None))
        self.assertEqual(found, ["lifecycle maintain needs a cron"])

    def test_cron_without_maintain_is_a_problem(self):
        found = _problems(_with(maintain=None))
        self.assertEqual(len(found), 1)
        self.assertIn("no maintain script", found[0])

    def test_a_cron_parse_cron_rejects_is_a_problem(self):
        found = _problems(_with(cron="61 * * * *"))
        self.assertEqual(len(found), 1)
        self.assertIn("invalid", found[0])

    def test_a_key_outside_the_shape_is_a_problem(self):
        lifecycle = _parse(BINDING.replace("region: optional", "Bad_Key: optional"))
        found = _problems(lifecycle)
        self.assertEqual(len(found), 1)
        self.assertIn("[a-z0-9-]+", found[0])

    def test_a_required_key_without_an_example_is_a_problem(self):
        lifecycle = _parse(BINDING.replace("config-example:\n  api-token: example-token\n", ""))
        found = _problems(lifecycle)
        self.assertEqual(len(found), 1)
        self.assertIn("no config-example", found[0])

    def test_two_keys_with_one_environment_name_are_a_problem(self):
        lifecycle = _parse(
            BINDING.replace("region: optional", "api_token: optional"))
        found = _problems(lifecycle)
        self.assertTrue(any("both map to LC_WORKFLOW_CONFIG_API_TOKEN" in p for p in found))


class TestEnv(unittest.TestCase):
    def setUp(self):
        self.lifecycle = _parse(BINDING)

    def _env(self, config, **kwargs):
        return workflow_script_env(
            {"PATH": "/bin"}, "install", "acme", "build", "/data/acme/build", "/bundle", "sha1",
            self.lifecycle, config, **kwargs)

    def test_a_declared_key_becomes_a_config_variable(self):
        env = self._env({"api-token": "secret"})
        self.assertEqual(env["LC_WORKFLOW_CONFIG_API_TOKEN"], "secret")
        self.assertEqual(env["LC_WORKFLOW_HOOK"], "install")
        self.assertEqual(env["LC_WORKFLOW_ORIGIN"], "acme")
        self.assertEqual(env["LC_WORKFLOW_NAME"], "build")
        self.assertEqual(env["LC_WORKFLOW_DATA_DIR"], "/data/acme/build")
        self.assertEqual(env["LC_WORKFLOW_BUNDLE_DIR"], "/bundle")
        self.assertEqual(env["LC_WORKFLOW_SHA"], "sha1")
        self.assertEqual(env["PATH"], "/bin")

    def test_a_blank_or_undeclared_key_is_omitted(self):
        env = self._env({"api-token": "  ", "region": "", "stray": "x"})
        self.assertNotIn("LC_WORKFLOW_CONFIG_API_TOKEN", env)
        self.assertNotIn("LC_WORKFLOW_CONFIG_REGION", env)
        self.assertNotIn("LC_WORKFLOW_CONFIG_STRAY", env)

    def test_from_and_to_sha_are_set_only_when_given(self):
        self.assertNotIn("LC_WORKFLOW_FROM_SHA", self._env({}))
        env = self._env({}, from_sha="old", to_sha="new")
        self.assertEqual((env["LC_WORKFLOW_FROM_SHA"], env["LC_WORKFLOW_TO_SHA"]), ("old", "new"))

    def test_missing_required_keys_names_blank_ones(self):
        self.assertEqual(missing_required_keys(self.lifecycle, {}), ("api-token",))
        self.assertEqual(missing_required_keys(self.lifecycle, {"api-token": " "}), ("api-token",))
        self.assertEqual(missing_required_keys(self.lifecycle, {"api-token": "x"}), ())
