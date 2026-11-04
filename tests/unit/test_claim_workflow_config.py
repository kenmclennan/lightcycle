import unittest

from lightcycle.application.flow.claim_step import ClaimStepUseCase
from lightcycle.config import ConfigError
from lightcycle.domain.workflows.lifecycle import parse_lifecycle, workflow_script_env
from lightcycle.frontmatter import split_frontmatter
from tests.support.lifecycle_fakes import LifecycleFakeConfig

PIN = "origin/wf@abc123"
DECLARED = """---
config:
  api-token: required
  region: optional
---
body
"""
UNDECLARED = "---\nentry: build\n---\nbody\n"


class StubFlow:
    def __init__(self, text):
        self.text = text

    def workflow_meta(self, pin):
        meta, _ = split_frontmatter(self.text)
        return meta


class CountingConfig(LifecycleFakeConfig):
    def __init__(self, blocks=None, error=None):
        super().__init__(blocks=blocks)
        self.reads = 0
        self.error = error

    def workflow_config(self, origin, name):
        self.reads += 1
        if self.error:
            raise self.error
        return super().workflow_config(origin, name)


def _uc(text, config):
    return ClaimStepUseCase(None, StubFlow(text), None, None, config, None)


class TestClaimWorkflowConfig(unittest.TestCase):
    BLOCK = {"workflow-origin-wf": {"api-token": "tok", "region": "   ", "stray": "x"}}

    def test_it_equals_the_script_path_values(self):
        config = CountingConfig(self.BLOCK)
        got = _uc(DECLARED, config)._workflow_config(PIN)
        meta, _ = split_frontmatter(DECLARED)
        env = workflow_script_env(
            {}, None, "origin", "wf", "/d", "/b", "abc123", parse_lifecycle(meta),
            config.workflow_config("origin", "wf"))
        exported = {k for k in env if k.startswith("LC_WORKFLOW_CONFIG_")}
        self.assertEqual(got, {"api-token": "tok"})
        self.assertEqual(exported, {"LC_WORKFLOW_CONFIG_API_TOKEN"})
        self.assertEqual(env["LC_WORKFLOW_CONFIG_API_TOKEN"], got["api-token"])

    def test_a_workflow_declaring_no_keys_is_empty_and_reads_no_config(self):
        config = CountingConfig(self.BLOCK)
        self.assertEqual(_uc(UNDECLARED, config)._workflow_config(PIN), {})
        self.assertEqual(config.reads, 0)

    def test_an_unpinned_claim_is_empty(self):
        config = CountingConfig(self.BLOCK)
        self.assertEqual(_uc(DECLARED, config)._workflow_config(None), {})
        self.assertEqual(config.reads, 0)

    def test_declared_keys_the_operator_did_not_set_are_empty(self):
        self.assertEqual(_uc(DECLARED, CountingConfig())._workflow_config(PIN), {})

    def test_only_the_set_key_appears(self):
        config = CountingConfig({"workflow-origin-wf": {"region": "eu"}})
        self.assertEqual(_uc(DECLARED, config)._workflow_config(PIN), {"region": "eu"})

    def test_a_config_error_is_empty(self):
        config = CountingConfig(self.BLOCK, error=ConfigError("unreadable"))
        self.assertEqual(_uc(DECLARED, config)._workflow_config(PIN), {})
