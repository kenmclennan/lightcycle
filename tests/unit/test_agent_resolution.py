import os
import tempfile
import unittest

from lightcycle.adapters.workflow_source import resolve_agent_for_pin


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


def _write_bundle_prompt(data, origin, sha, role, model="sonnet", body="do the thing"):
    steps = os.path.join(data, "workflows", origin, sha, "steps")
    os.makedirs(steps, exist_ok=True)
    with open(os.path.join(steps, "%s.md" % role), "w") as f:
        f.write("---\nmodel: %s\n---\n\n%s\n" % (model, body))


class TestResolveAgentForPin(unittest.TestCase):
    def test_pin_none_resolves_from_prompts_root(self):
        prompts, data = tempfile.mkdtemp(), tempfile.mkdtemp()
        _write_prompt(prompts, "audit", model="haiku")
        agent = resolve_agent_for_pin(_Cfg(prompts, data), "audit", None)
        self.assertIsNotNone(agent)
        self.assertEqual(agent["meta"].get("model"), "haiku")

    def test_pin_none_does_not_search_any_bundle(self):
        prompts, data = tempfile.mkdtemp(), tempfile.mkdtemp()
        _write_bundle_prompt(data, "lightcycle", "sha1", "write-code")
        self.assertIsNone(resolve_agent_for_pin(_Cfg(prompts, data), "write-code", None))

    def test_resolves_from_the_pinned_bundle(self):
        prompts, data = tempfile.mkdtemp(), tempfile.mkdtemp()
        _write_bundle_prompt(data, "lightcycle", "sha1", "write-code", model="opus")
        agent = resolve_agent_for_pin(
            _Cfg(prompts, data), "write-code", "lightcycle/spec-driven@sha1")
        self.assertIsNotNone(agent)
        self.assertEqual(agent["meta"].get("model"), "opus")

    def test_pin_honours_its_sha_over_a_drifted_sibling(self):
        prompts, data = tempfile.mkdtemp(), tempfile.mkdtemp()
        _write_bundle_prompt(data, "lightcycle", "sha1", "write-code", model="opus")
        _write_bundle_prompt(data, "lightcycle", "sha2", "write-code", model="sonnet")
        agent = resolve_agent_for_pin(
            _Cfg(prompts, data), "write-code", "lightcycle/spec-driven@sha1")
        self.assertEqual(agent["meta"].get("model"), "opus")

    def test_prompts_root_wins_over_the_bundle(self):
        prompts, data = tempfile.mkdtemp(), tempfile.mkdtemp()
        _write_prompt(prompts, "write-code", model="haiku")
        _write_bundle_prompt(data, "lightcycle", "sha1", "write-code", model="opus")
        agent = resolve_agent_for_pin(
            _Cfg(prompts, data), "write-code", "lightcycle/spec-driven@sha1")
        self.assertEqual(agent["meta"].get("model"), "haiku")

    def test_unknown_role_returns_none(self):
        prompts, data = tempfile.mkdtemp(), tempfile.mkdtemp()
        _write_bundle_prompt(data, "lightcycle", "sha1", "write-code")
        self.assertIsNone(resolve_agent_for_pin(
            _Cfg(prompts, data), "nonesuch", "lightcycle/spec-driven@sha1"))


if __name__ == "__main__":
    unittest.main()
