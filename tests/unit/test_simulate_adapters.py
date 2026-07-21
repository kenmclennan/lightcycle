import unittest

from lightcycle.adapters.simulate import NullWorkers, RecordingGit, ScriptedGitHub, SimulateConfig
from lightcycle.config import Config


class TestRecordingGit(unittest.TestCase):
    def test_create_then_teardown_round_trips(self):
        git = RecordingGit()
        git.git("/repo", "worktree", "add", "/repo/.worktrees/LC-1", "--no-track", "-b",
                "feat/lc-1", "main")
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
        git.git("/repo", "worktree", "add", "/repo/.worktrees/LC-2", "--no-track", "-b",
                "feat/lc-2", "main")
        self.assertIn(("/repo", "/repo/.worktrees/LC-2"), git.created_worktrees())
        self.assertNotIn(("/repo", "/repo/.worktrees/LC-2"), git.torn_down_worktrees())
        self.assertIn(("/repo", "feat/lc-2"), git.created_branches())
        self.assertNotIn(("/repo", "feat/lc-2"), git.torn_down_branches())


class TestScriptedGitHub(unittest.TestCase):
    def test_script_merge_fires_once(self):
        gh = ScriptedGitHub()
        gh.script_merge("pr-1")
        self.assertTrue(gh.is_merged("pr-1"))
        self.assertFalse(gh.is_merged("pr-1"))

    def test_script_conflict_fires_once(self):
        gh = ScriptedGitHub()
        gh.script_conflict("pr-1")
        self.assertTrue(gh.is_conflicted("pr-1"))
        self.assertFalse(gh.is_conflicted("pr-1"))

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


class TestNullWorkers(unittest.TestCase):
    def test_every_method_raises(self):
        workers = NullWorkers()
        with self.assertRaises(AssertionError):
            workers.workers_state()
        with self.assertRaises(AssertionError):
            workers.write_workers({})
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
        sim = SimulateConfig(real, "/scratch/specs", "/scratch/projects")
        self.assertIsNone(sim.spawn_id())

    def test_specs_and_projects_root_are_the_scratch_paths(self):
        real = Config(environ={"LC_HOME": "/real/home"})
        sim = SimulateConfig(real, "/scratch/specs", "/scratch/projects")
        self.assertEqual(sim.specs_root(), "/scratch/specs")
        self.assertEqual(sim.projects_root(), "/scratch/projects")

    def test_other_config_reads_delegate_to_the_real_config(self):
        real = Config(environ={"LC_HOME": "/real/home", "LC_MAX_AGENTS": "7"})
        sim = SimulateConfig(real, "/scratch/specs", "/scratch/projects")
        self.assertEqual(sim.max_agents(), 7)
        self.assertEqual(sim.data_root(), "/real/home")


if __name__ == "__main__":
    unittest.main()
