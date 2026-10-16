import unittest

from lightcycle.application.workflows.simulate import WorkflowSimulateUseCase
from lightcycle.ports.lifecycle_runner import HookResult
from tests.support.fake_git import FakeGit
from tests.unit.test_workflow_lifecycle_usecases import Harness, workflow_text


def _simulate(h):
    return WorkflowSimulateUseCase(
        None, None, None, None, None, "/scratch/projects", FakeGit(), lifecycle=h.lifecycle,
        scripts=None, source=None)


class TestSimulateLifecycle(unittest.TestCase):
    def _added(self, text):
        h = Harness(blocks={"workflow-acme-build": {"api-token": "LIVE-SECRET"}})
        h.remote("sha1", {"build": text})
        h.add()
        h.runner.calls.clear()
        return h

    def test_install_upgrade_maintain_run_in_order_in_a_scratch_dir(self):
        h = self._added(workflow_text(maintain=True))
        trace = []
        violations = _simulate(h)._run_lifecycle("acme/build@sha1", trace)
        self.assertEqual(violations, [])
        self.assertEqual(
            [c["env"]["LC_WORKFLOW_HOOK"] for c in h.runner.calls],
            ["install", "upgrade", "maintain"])
        self.assertEqual(trace, [
            "lifecycle install: ok", "lifecycle upgrade: ok", "lifecycle maintain: ok"])
        for call in h.runner.calls:
            self.assertEqual(call["cwd"], "/scratch/lifecycle-data/acme/build")

    def test_upgrade_goes_from_the_pinned_sha_to_itself(self):
        h = self._added(workflow_text(maintain=True))
        _simulate(h)._run_lifecycle("acme/build@sha1", [])
        env = h.runner.calls[1]["env"]
        self.assertEqual((env["LC_WORKFLOW_FROM_SHA"], env["LC_WORKFLOW_TO_SHA"]), ("sha1", "sha1"))
        self.assertNotIn("LC_WORKFLOW_FROM_SHA", h.runner.calls[0]["env"])

    def test_config_comes_from_the_examples_never_the_live_block(self):
        h = self._added(workflow_text(maintain=True))
        _simulate(h)._run_lifecycle("acme/build@sha1", [])
        for call in h.runner.calls:
            self.assertEqual(call["env"]["LC_WORKFLOW_CONFIG_API_TOKEN"], "example")

    def test_a_non_zero_exit_is_a_violation_and_stops_the_sequence(self):
        h = self._added(workflow_text(maintain=True))
        h.runner.program("upgrade", HookResult(exit_code=4, output="nope"))
        violations = _simulate(h)._run_lifecycle("acme/build@sha1", [])
        self.assertEqual(len(violations), 1)
        self.assertIn("lifecycle upgrade", violations[0])
        self.assertIn("exited 4: nope", violations[0])
        self.assertEqual(
            [c["env"]["LC_WORKFLOW_HOOK"] for c in h.runner.calls], ["install", "upgrade"])

    def test_a_workflow_without_a_lifecycle_runs_nothing(self):
        h = Harness()
        h.remote("sha1", {"build": "entry: code\n"}, scripts={})
        h.add()
        self.assertEqual(_simulate(h)._run_lifecycle("acme/build@sha1", []), [])
        self.assertEqual(h.runner.calls, [])
