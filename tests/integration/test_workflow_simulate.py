import os
import shutil
import tempfile
import unittest
from pathlib import Path

import lightcycle.cli as cli
from lightcycle.adapters.simulate import NullWorkers, RecordingGit, SimulateConfig
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.application.flow.claim_step import ClaimStepUseCase
from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.workflows.simulate import SimulateInput, WorkflowSimulateUseCase
from lightcycle.config import Config
from lightcycle.container import Container, make_flow_service, make_worktrees
from lightcycle.domain.runs.phase_run import RunState

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

_EDGE_PASS_END_TEXT = _WORKFLOW_TEXT.replace(
    "  await-merge       merged       cleanup\n",
    "  await-merge       merged       cleanup\n"
    "  cleanup           done         write-code\n",
).replace(
    "  mention_token         await-merge  @lc\n",
    "  mention_token         await-merge  @lc\n"
    "\n"
    "pass-end:\n"
    "  cleanup  done\n",
)

_HOOK_PASS_END_TEXT = _WORKFLOW_TEXT + (
    "\npass-end:\n"
    "  await-merge  merged\n"
)

_STUCK_LOOP_WORKFLOW_TEXT = """entry: build

requires: brief repo

edges:
  build   done   review
  review  done   finish
  review  loop   stuck
  stuck   done   stuck
"""

_STUCK_LOOP_STEPS = {
    "build": "---\nmodel: sonnet\naccepts:\n  brief: required\nproduces:\n  branch: required\n"
             "---\n\nBuild.\n",
    "review": "---\nmodel: sonnet\naccepts:\n  branch: required\n---\n\nReview.\n",
    "finish": "Finish, terminal, no routes.\n",
    "stuck": "---\nmodel: sonnet\n---\n\nStuck.\n",
}

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


_TWO_PHASE_WORKFLOW_TEXT = """entry: spec-writer

requires: brief repo

phase:
  spec-writer       spec
  spec-open-pr      spec
  spec-await-merge  spec
  write-code        code
  code-open-pr      code
  code-await-merge  code
  cleanup           code

nodes:
  spec-open-pr      open-pr
  code-open-pr      open-pr
  spec-await-merge  await-merge
  code-await-merge  await-merge

edges:
  spec-writer       done         spec-open-pr
  spec-open-pr      done         spec-await-merge
  spec-await-merge  spec-merged  write-code
  spec-await-merge  changes      spec-writer
  write-code        done         code-open-pr
  code-open-pr      done         code-await-merge
  code-await-merge  merged       cleanup
  code-await-merge  changes      write-code

hooks:
  pr_merge  spec-await-merge  spec-merged
  pr_merge  code-await-merge  merged
"""

_TWO_PHASE_STEPS = {
    "spec-writer": "---\nmodel: sonnet\naccepts:\n  brief: required\nproduces:\n  spec: required\n"
                   "---\n\nWrite the spec.\n",
    "write-code": "---\nmodel: sonnet\naccepts:\n  spec: required\nproduces:\n  branch: required\n"
                  "---\n\nWrite the code.\n",
    "open-pr": "---\nmodel: sonnet\naccepts:\n  branch: optional\nproduces:\n  pr: required\n"
               "  branch: required\n---\n\nOpen a PR.\n",
    "await-merge": "Await merge.\n",
    "cleanup": "Cleanup, terminal, no routes.\n",
}


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

    def _run_direct(self, workflow_text, steps):
        selector = self._install(workflow_text, steps)
        c = cli._container
        scratch = tempfile.mkdtemp(prefix="lc-simulate-test-")
        self.addCleanup(lambda: shutil.rmtree(scratch, ignore_errors=True))
        store_home = os.path.join(scratch, "home")
        specs_root = os.path.join(scratch, "specs")
        projects_root = os.path.join(scratch, "projects")
        os.makedirs(store_home, exist_ok=True)
        os.makedirs(specs_root, exist_ok=True)
        os.makedirs(projects_root, exist_ok=True)
        cfg_path = os.path.join(store_home, "config")
        with open(cfg_path, "w") as f:
            f.write("shortcode: SIM\n")
        store_config = Config(environ={"LC_HOME": store_home, "LC_CONFIG": cfg_path})
        store = SqliteStore(store_config)
        sim_config = SimulateConfig(c.config, specs_root, projects_root)
        git = RecordingGit()
        flow = make_flow_service(c.fs, store, c.config, c.workflow_source)
        worktrees = make_worktrees(store, git, c.fs, sim_config, flow)
        claim = ClaimStepUseCase(store, flow, worktrees, NullWorkers(), sim_config)
        complete = CompleteStepUseCase(store, flow, worktrees, sim_config)
        use_case = WorkflowSimulateUseCase(
            store, flow, worktrees, claim, complete, projects_root, git
        )
        resp = use_case.execute(SimulateInput(workflow=selector))
        return resp, store


class TestGoodBundlePasses(SimulateTestCase):
    def test_simulate_passes_and_closes_every_walk(self):
        selector = self._install(_WORKFLOW_TEXT, _STEPS)
        rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 0)


_WORKFLOW_TEXT_PHASED = _WORKFLOW_TEXT.replace(
    "edges:\n",
    "phase:\n"
    "  write-code        code\n"
    "  open-pr           code\n"
    "  watch-ci          code\n"
    "  review-code       code\n"
    "  await-merge       code\n"
    "  cleanup           code\n"
    "  resolve-conflict  code\n"
    "  review-ci         code\n"
    "  handle-feedback   code\n"
    "\n"
    "edges:\n",
    1,
)


class TestPhasedGoodBundlePasses(SimulateTestCase):
    def test_pr_feedback_and_ci_failed_cap_with_matching_phases_still_passes(self):
        selector = self._install(_WORKFLOW_TEXT_PHASED, _STEPS)

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


class TestPlannerIncompleteWalkIsNotADrivingFailure(SimulateTestCase):
    def test_a_walk_with_no_reachable_terminal_is_reported_without_driving(self):
        import io
        from contextlib import redirect_stderr

        selector = self._install(_STUCK_LOOP_WORKFLOW_TEXT, _STUCK_LOOP_STEPS)
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 1)
        output = err.getvalue()
        self.assertIn("stuck", output)
        self.assertNotIn("did not terminate", output)
        self.assertNotIn("teardown:", output)


_HANDOFF_WORKFLOW_TEXT = """entry: build

requires: brief repo

edges:
  build    done        review
  build    ci-failed   build
  review   done        finish

hooks:
  ci_failed_cap   build   ci-failed   1   gate
"""

_HANDOFF_STEPS = {
    "build": "---\nmodel: sonnet\naccepts:\n  brief: required\n---\n\nBuild.\n",
    "review": "---\nmodel: sonnet\nproduces:\n  widget: required\n---\n\nReview.\n",
    "finish": "Finish, terminal, no routes.\n",
    "gate": "---\nmodel: sonnet\naccepts:\n  widget: required\n---\n\nGate.\n",
}


class TestHandoffSatisfactionViolation(SimulateTestCase):
    def test_a_branch_that_skips_the_producer_is_a_violation(self):
        selector = self._install(_HANDOFF_WORKFLOW_TEXT, _HANDOFF_STEPS)
        rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 1)

    def test_use_case_reports_the_offending_claim(self):
        import io
        from contextlib import redirect_stderr

        selector = self._install(_HANDOFF_WORKFLOW_TEXT, _HANDOFF_STEPS)
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 1)
        output = err.getvalue()
        self.assertIn("widget", output)
        self.assertRegex(
            output,
            r"walk \d+: could not claim stage 'gate': "
            r"BLOCKED: missing required input\(s\): widget",
        )


if __name__ == "__main__":
    unittest.main()


class TestTwoPhaseBundleSeedsAPrPerPhase(SimulateTestCase):
    def test_merging_one_phases_pr_does_not_merge_the_other_phases(self):
        selector = self._install(_TWO_PHASE_WORKFLOW_TEXT, _TWO_PHASE_STEPS)

        rc = cli._workflow_simulate(selector)

        self.assertEqual(rc, 0)


class TestEdgeKindPassEndPasses(SimulateTestCase):
    def test_a_looping_workflows_edge_kind_pass_end_is_simulated_cleanly(self):
        selector = self._install(_EDGE_PASS_END_TEXT, _STEPS)
        rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 0)


class TestHookKindPassEndPasses(SimulateTestCase):
    def test_a_looping_workflows_hook_kind_pass_end_is_simulated_cleanly(self):
        selector = self._install(_HOOK_PASS_END_TEXT, _STEPS)
        rc = cli._workflow_simulate(selector)
        self.assertEqual(rc, 0)


class TestPassBoundaryClosesPassOneAndMergesItsRuns(SimulateTestCase):
    def test_crossing_the_pass_end_closes_pass_one_with_every_run_merged(self):
        resp, store = self._run_direct(_EDGE_PASS_END_TEXT, _STEPS)
        self.assertTrue(resp.ok, resp.violations)

        multi_pass_items = [
            item for item in store.all_items_including_done()
            if len(store.passes_of(item.id)) >= 2
        ]
        self.assertTrue(multi_pass_items)
        item = multi_pass_items[0]
        passes = sorted(store.passes_of(item.id), key=lambda p: p.n)
        pass1 = passes[0]
        self.assertEqual(pass1.state, "closed")
        for run in store.runs_of(item.id, pass1.id):
            self.assertEqual(run.state, RunState.MERGED)


class TestPreExistingSimulateFixturesStillPassUnmodified(SimulateTestCase):
    def test_good_bundle_still_passes(self):
        selector = self._install(_WORKFLOW_TEXT, _STEPS)
        self.assertEqual(cli._workflow_simulate(selector), 0)

    def test_phased_good_bundle_still_passes(self):
        selector = self._install(_WORKFLOW_TEXT_PHASED, _STEPS)
        self.assertEqual(cli._workflow_simulate(selector), 0)

    def test_routing_soundness_violation_still_fires(self):
        selector = self._install(_NO_ESCALATE_EDGE_WORKFLOW_TEXT, _STEPS)
        self.assertEqual(cli._workflow_simulate(selector), 1)

    def test_teardown_violation_still_surfaces_from_a_stuck_walk(self):
        steps = dict(_STEPS)
        steps["review-ci"] = _MISSING_INPUT_REVIEW_CI
        selector = self._install(_WORKFLOW_TEXT, steps)
        self.assertEqual(cli._workflow_simulate(selector), 1)
