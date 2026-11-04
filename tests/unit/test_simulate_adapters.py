import unittest

from lightcycle.adapters.simulate import NullWorkers, RecordingGit, ScriptedGitHub, SimulateConfig
from lightcycle.config import Config
from lightcycle.ports.git import RESTACK_PUSHED, GitOutcome, RestackStep
from lightcycle.ports.github import PrView, ReadFailure


class TestRecordingGit(unittest.TestCase):
    def test_create_then_teardown_round_trips(self):
        git = RecordingGit()
        git.add_worktree("/repo", "/repo/.worktrees/LC-1", "feat/lc-1", "main")
        self.assertIn(("/repo", "/repo/.worktrees/LC-1"), git.created_worktrees())
        self.assertIn(("/repo", "feat/lc-1"), git.created_branches())
        self.assertTrue(git.worktree_registered("/repo", "/repo/.worktrees/LC-1"))
        self.assertTrue(git.branch_exists("/repo", "feat/lc-1"))

        git.remove_worktree("/repo", "/repo/.worktrees/LC-1")
        git.delete_branch("/repo", "feat/lc-1")
        git.delete_remote_branch("/repo", "feat/lc-1")

        self.assertIn(("/repo", "/repo/.worktrees/LC-1"), git.torn_down_worktrees())
        self.assertIn(("/repo", "feat/lc-1"), git.torn_down_branches())
        self.assertIn(("/repo", "feat/lc-1"), git.torn_down_remote_branches())
        self.assertFalse(git.worktree_registered("/repo", "/repo/.worktrees/LC-1"))
        self.assertFalse(git.branch_exists("/repo", "feat/lc-1"))

    def test_create_with_no_teardown_is_distinguishable(self):
        git = RecordingGit()
        git.add_worktree("/repo", "/repo/.worktrees/LC-2", "feat/lc-2", "main")
        self.assertIn(("/repo", "/repo/.worktrees/LC-2"), git.created_worktrees())
        self.assertNotIn(("/repo", "/repo/.worktrees/LC-2"), git.torn_down_worktrees())
        self.assertIn(("/repo", "feat/lc-2"), git.created_branches())
        self.assertNotIn(("/repo", "feat/lc-2"), git.torn_down_branches())

    def test_prune_set_upstream_and_init_repo_record_and_succeed(self):
        git = RecordingGit()

        self.assertEqual(git.prune_worktrees("/repo"), GitOutcome(ok=True))
        self.assertEqual(git.set_branch_upstream("/repo", "feat/lc-1"), GitOutcome(ok=True))
        self.assertEqual(git.init_repo("/repo", "main"), GitOutcome(ok=True))

        self.assertIn(("/repo", "prune_worktrees", ()), git.calls)
        self.assertIn(("/repo", "set_branch_upstream", ("feat/lc-1", "origin")), git.calls)
        self.assertIn(("/repo", "init_repo", ("main",)), git.calls)


class TestScriptedGitHub(unittest.TestCase):
    def test_it_reports_a_settable_login_and_keys_scripted_feedback(self):
        gh = ScriptedGitHub(login="ken")
        self.assertEqual(gh.authenticated_login(), "ken")
        gh.script_feedback("pr1", "@lc one")
        gh.script_feedback("pr1", "@lc two", author="mallory")
        ids = [c.id for c in gh.comments_since("pr1", 0.0)]
        self.assertEqual(len(set(ids)), 2)
        self.assertNotIn(None, ids)

    def test_script_merge_fires_once(self):
        gh = ScriptedGitHub()
        gh.script_merge("pr-1")
        self.assertTrue(gh.is_merged("pr-1"))
        self.assertFalse(gh.is_merged("pr-1"))

    def test_script_conflict_fires_once(self):
        gh = ScriptedGitHub()
        gh.script_conflict("pr-1")
        self.assertTrue(gh.pr_sync_state("pr-1").conflicted)
        self.assertFalse(gh.pr_sync_state("pr-1").conflicted)

    def test_two_instances_never_share_state(self):
        a, b = ScriptedGitHub(), ScriptedGitHub()
        a.script_merge("pr-1")
        self.assertFalse(b.is_merged("pr-1"))
        self.assertTrue(a.is_merged("pr-1"))

    def test_script_feedback_is_returned_once_then_gone(self):
        gh = ScriptedGitHub()
        gh.script_feedback("pr-1", "please fix x")
        comments = gh.comments_since("pr-1", 0.0)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0].body, "please fix x")
        self.assertEqual(gh.comments_since("pr-1", 0.0), [])


class TestScriptedGitHubStack(unittest.TestCase):
    def test_set_pr_base_is_recorded_and_returns_none(self):
        gh = ScriptedGitHub()
        gh.open_pr("pr-2", "feat/s1")
        gh.script_merged("pr-1")

        result = gh.set_pr_base("pr-2", "main")

        self.assertIsNone(result)
        self.assertEqual(gh.base_edits, [("pr-2", "main", frozenset({"pr-1"}))])
        self.assertEqual(gh.pr_view("pr-2").base_ref, "main")

    def test_pr_view_of_an_unopened_pr_is_still_a_read_failure(self):
        self.assertIsInstance(ScriptedGitHub().pr_view("pr-9"), ReadFailure)

    def test_pr_view_of_an_opened_pr_reports_base_and_head(self):
        gh = ScriptedGitHub()
        gh.open_pr("pr-1", "main")
        gh.script_head("pr-1", "abc")

        view = gh.pr_view("pr-1")

        self.assertEqual(view, PrView("OPEN", "abc", "main", "main", "MERGEABLE", "CLEAN", 0.0))
        self.assertEqual(gh.head_sha("pr-1"), "abc")

    def test_head_sha_defaults_to_the_constant(self):
        self.assertEqual(ScriptedGitHub().head_sha("pr-1"), "sim-sha")

    def test_script_merged_persists_while_script_merge_still_fires_once(self):
        gh = ScriptedGitHub()
        gh.script_merged("pr-1")
        gh.script_merge("pr-2")

        self.assertTrue(gh.is_merged("pr-1"))
        self.assertTrue(gh.is_merged("pr-1"))
        self.assertTrue(gh.is_merged("pr-2"))
        self.assertFalse(gh.is_merged("pr-2"))


class TestRecordingGitTips(unittest.TestCase):
    def test_ref_sha_is_the_constant_for_an_unknown_branch(self):
        self.assertEqual(RecordingGit().ref_sha("/repo", "origin/feat/x"), "sim-sha")

    def test_ref_sha_reads_the_set_tip_with_or_without_origin(self):
        git = RecordingGit()
        git.set_tip("feat/x", "tip-1")

        self.assertEqual(git.ref_sha("/repo", "origin/feat/x"), "tip-1")
        self.assertEqual(git.ref_sha("/repo", "feat/x"), "tip-1")

    def test_restack_records_the_call_sets_fresh_tips_and_returns_them(self):
        git = RecordingGit()
        steps = [
            RestackStep("feat/a", "l1", "b1", "origin/main"),
            RestackStep("feat/b", "l2", "b2", "feat/a"),
        ]

        outcome = git.restack("/repo", steps)

        self.assertEqual(outcome.kind, RESTACK_PUSHED)
        self.assertEqual(outcome.tips, {"feat/a": "sim-sha-1", "feat/b": "sim-sha-2"})
        self.assertEqual(git.ref_sha("/repo", "origin/feat/b"), "sim-sha-2")
        self.assertEqual(git.restack_calls(), [tuple(steps)])


class TestNullWorkers(unittest.TestCase):
    def test_every_method_raises(self):
        workers = NullWorkers()
        with self.assertRaises(AssertionError):
            workers.workers_state()
        with self.assertRaises(AssertionError):
            workers.pid_alive(1)
        with self.assertRaises(AssertionError):
            workers.reap()
        with self.assertRaises(AssertionError):
            workers.kill(1)
        with self.assertRaises(AssertionError):
            workers.prune_workers()
        with self.assertRaises(AssertionError):
            workers.set_step("s", "t")
        with self.assertRaises(AssertionError):
            workers.step_for("s")
        with self.assertRaises(AssertionError):
            workers.mark_checked("s")


class TestSimulateConfig(unittest.TestCase):
    def test_spawn_id_is_none_even_when_env_set(self):
        real = Config(environ={"LC_SPAWNID": "worker-9"})
        sim = SimulateConfig(real, "/scratch/projects")
        self.assertIsNone(sim.spawn_id())

    def test_projects_root_is_the_scratch_path(self):
        real = Config(environ={"LC_HOME": "/real/home"})
        sim = SimulateConfig(real, "/scratch/projects")
        self.assertEqual(sim.projects_root(), "/scratch/projects")

    def test_other_config_reads_delegate_to_the_real_config(self):
        real = Config(environ={"LC_HOME": "/real/home", "LC_MAX_AGENTS": "7"})
        sim = SimulateConfig(real, "/scratch/projects")
        self.assertEqual(sim.max_agents(), 7)
        self.assertEqual(sim.data_root(), "/real/home")


if __name__ == "__main__":
    unittest.main()
