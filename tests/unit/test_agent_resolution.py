import os
import tempfile
import unittest
from unittest.mock import patch

from lightcycle.adapters.workflow_source import agent_search_roots, resolve_agent

_BUNDLE_FN = "lightcycle.adapters.workflow_source.default_bundle_root"


class _Cfg:
    def __init__(self, prompts, data):
        self._prompts = prompts
        self._data = data

    def prompts_root(self):
        return self._prompts

    def data_root(self):
        return self._data

    def default_origin(self):
        return "lightcycle"


def _write_prompt(root, role, model="sonnet", body="do the thing"):
    steps = os.path.join(root, "steps")
    os.makedirs(steps, exist_ok=True)
    with open(os.path.join(steps, "%s.md" % role), "w") as f:
        f.write("---\nmodel: %s\n---\n\n%s\n" % (model, body))


class TestAgentSearchRoots(unittest.TestCase):
    def _cfg(self):
        return _Cfg(tempfile.mkdtemp(), tempfile.mkdtemp())

    def test_prompts_root_comes_first_then_bundle(self):
        cfg = self._cfg()
        with patch(_BUNDLE_FN, return_value="/tmp/bundle-x"):
            self.assertEqual(agent_search_roots(cfg), [cfg.prompts_root(), "/tmp/bundle-x"])

    def test_bundle_omitted_when_none(self):
        cfg = self._cfg()
        with patch(_BUNDLE_FN, return_value=None):
            self.assertEqual(agent_search_roots(cfg), [cfg.prompts_root()])


class TestResolveAgent(unittest.TestCase):
    def test_finds_engine_owned_prompt_absent_from_bundle(self):
        prompts = tempfile.mkdtemp()
        _write_prompt(prompts, "audit")
        cfg = _Cfg(prompts, tempfile.mkdtemp())
        with patch(_BUNDLE_FN, return_value=None):
            agent = resolve_agent(cfg, "audit")
        self.assertIsNotNone(agent)
        self.assertEqual(agent["meta"].get("model"), "sonnet")

    def test_returns_none_for_unknown_role(self):
        cfg = _Cfg(tempfile.mkdtemp(), tempfile.mkdtemp())
        with patch(_BUNDLE_FN, return_value=None):
            self.assertIsNone(resolve_agent(cfg, "nonesuch"))


if __name__ == "__main__":
    unittest.main()
