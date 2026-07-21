import os
import tempfile
import unittest
from pathlib import Path

import lightcycle.cli as cli
from lightcycle.config import Config
from lightcycle.container import Container

_WORKFLOW_TEXT = """entry: write-code

requires: brief repo

edges:
  write-code        done         open-pr
  open-pr           done         watch-ci
  watch-ci          done         review-code
  watch-ci          ci-failed    write-code
  review-code       done         await-merge
  review-code       rejected     write-code
  await-merge       changes      write-code
  await-merge       merged       cleanup
  await-merge       conflicted   resolve-conflict
  await-merge       gave-up      review-conflict
  resolve-conflict  resolved     open-pr
  resolve-conflict  escalate     review-conflict

hooks:
  pr_merge              await-merge  merged
  pr_conflict           await-merge  conflicted
  pr_conflict_cap       await-merge  2
  pr_conflict_escalate  await-merge  gave-up
  pr_feedback           await-merge  handle-feedback
  ci_failed_cap         watch-ci     ci-failed  2  review-ci
  mention_token         await-merge  @lc
"""

_NO_ESCALATE_EDGE_WORKFLOW_TEXT = _WORKFLOW_TEXT.replace(
    "  await-merge       gave-up      review-conflict\n", ""
)

_STEPS = {
    "write-code": "---\nmodel: sonnet\naccepts:\n  brief: required\nproduces:\n  branch: required\n"
                  "---\n\nWrite the code.\n",
    "open-pr": "---\nmodel: sonnet\naccepts:\n  branch: optional\nproduces:\n  pr: required\n"
               "  branch: required\n---\n\nOpen a PR.\n",
    "watch-ci": "---\nmodel: sonnet\naccepts:\n  pr: required\nproduces:\n  branch: required\n"
                "---\n\nWatch CI.\n",
    "review-code": "---\nmodel: sonnet\naccepts:\n  branch: required\n---\n\nReview the code.\n",
    "await-merge": "Await merge.\n",
    "cleanup": "Cleanup, terminal, no routes.\n",
    "resolve-conflict": "---\nmodel: sonnet\n---\n\nResolve the conflict.\n",
    "review-ci": "Review CI failures, terminal, no routes.\n",
    "handle-feedback": "---\nmodel: sonnet\n---\n\nHandle feedback.\n",
}

_MISSING_INPUT_REVIEW_CI = (
    "---\naccepts:\n  spec: required\n---\n\nReview CI failures, terminal, no routes.\n"
)


def _seed_config(home):
    lines = [
        "projects: %s" % os.path.join(home, "projects"),
        "specs: %s" % os.path.join(home, "specs"),
        "shortcode: SIM",
        "branch-prefix: feat",
        "default-origin: acme",
        "max-agents: 5",
        "worktree-retries: 1",
        "worktree-retry-sleep: 0.01",
        "max-boot-seconds: 120",
        "poll-seconds: 5",
        "worker-history: 20",
        "editor: vi",
        "retro-interval-reflections: 20",
        "backups-dir: %s" % os.path.join(home, "backups"),
        "backup-interval-minutes: 15",
        "backup-retention: 96",
        "max-title-length: 72",
    ]
    cfg_path = os.path.join(home, "config")
    Path(cfg_path).write_text("".join(l + "\n" for l in lines))
    return cfg_path


def _write_bundle(home, origin, sha, workflow_text, steps):
    bundle = Path(home) / "workflows" / origin / sha
    (bundle / "workflows").mkdir(parents=True)
    (bundle / "steps").mkdir(parents=True)
    (bundle / "source.toml").write_text('name = "%s"\ncontract = 1\n' % origin)
    (bundle / "workflows" / "build.md").write_text(workflow_text)
    for name, text in steps.items():
        (bundle / "steps" / ("%s.md" % name)).write_text(text)
    origin_dir = Path(home) / "workflows" / origin
    (origin_dir / "origin.toml").write_text(
        'url = "local"\nref = "main"\ncurrent = "%s"\n' % sha
    )


class SimulateTestCase(unittest.TestCase):
    def setUp(self):
        self._orig = cli._container
        self.addCleanup(lambda: cli.set_container(self._orig))

    def _install(self, workflow_text, steps):
        home = tempfile.mkdtemp()
        cfg_path = _seed_config(home)
        _write_bundle(home, "acme", "sha1", workflow_text, steps)
        config = Config(environ={"LC_HOME": home, "LC_CONFIG": cfg_path})
        cli.set_container(Container(config=config))
        return "acme/build"


class TestGoodBundlePasses(SimulateTestCase):
    def test_simulate_passes_and_closes_every_walk(self):
        selector = self._install(_WORKFLOW_TEXT, _STEPS)
        rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 0)


class TestCmdWorkflowSimulateDispatch(SimulateTestCase):
    def test_cmd_workflow_simulate_dispatches_and_prints_pass(self):
        import io
        from contextlib import redirect_stdout

        selector = self._install(_WORKFLOW_TEXT, _STEPS)
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.cmd_workflow(["simulate", selector])
        self.assertEqual(rc, 0)
        self.assertIn("pass", out.getvalue())

    def test_cmd_workflow_simulate_dispatches_violations_and_nonzero(self):
        import io
        from contextlib import redirect_stderr

        selector = self._install(_NO_ESCALATE_EDGE_WORKFLOW_TEXT, _STEPS)
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli.cmd_workflow(["simulate", selector])
        self.assertEqual(rc, 1)
        self.assertIn("gave-up", err.getvalue())


class TestRoutingSoundnessViolation(SimulateTestCase):
    def test_conflict_escalation_to_an_undeclared_outcome_is_a_violation(self):
        selector = self._install(_NO_ESCALATE_EDGE_WORKFLOW_TEXT, _STEPS)
        rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 1)

    def test_use_case_reports_the_offending_transition(self):
        import io
        from contextlib import redirect_stderr

        selector = self._install(_NO_ESCALATE_EDGE_WORKFLOW_TEXT, _STEPS)
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 1)
        output = err.getvalue()
        self.assertIn("gave-up", output)
        self.assertRegex(output, r"walk \d+: await-merge\[pr_conflict hook\] raised: .*gave-up")

    def test_the_dead_end_does_not_abort_remaining_walks_or_teardown(self):
        import io
        from contextlib import redirect_stderr

        selector = self._install(_NO_ESCALATE_EDGE_WORKFLOW_TEXT, _STEPS)
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 1)
        output = err.getvalue()
        self.assertIn("did not terminate", output)
        self.assertIn("teardown:", output)


class TestTeardownViolationSurfacesFromAStuckWalk(SimulateTestCase):
    def test_a_walk_that_never_closes_leaves_a_leaked_worktree(self):
        import io
        from contextlib import redirect_stderr

        steps = dict(_STEPS)
        steps["review-ci"] = _MISSING_INPUT_REVIEW_CI
        selector = self._install(_WORKFLOW_TEXT, steps)
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 1)
        output = err.getvalue()
        self.assertIn("teardown", output)
        self.assertIn("could not claim stage 'review-ci'", output)


if __name__ == "__main__":
    unittest.main()
