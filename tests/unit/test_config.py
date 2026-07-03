import os
import tempfile
import unittest
from pathlib import Path

from the_grid.config import Config, ConfigError

HOME = os.path.expanduser("~")


def _cfg(environ=None, **filevals):
    env = dict(environ or {})
    if filevals:
        p = os.path.join(tempfile.mkdtemp(), "config")
        Path(p).write_text(
            "".join("%s: %s\n" % (k.replace("_", "-"), v) for k, v in filevals.items())
        )
        env["GRID_CONFIG"] = p
    else:
        env.setdefault("GRID_CONFIG", os.path.join(tempfile.mkdtemp(), "absent"))
    return Config(environ=env)


class TestRequiredRoots(unittest.TestCase):
    def test_projects_missing_fails_fast_naming_key_and_path(self):
        c = _cfg()
        with self.assertRaises(ConfigError) as ctx:
            c.projects_root()
        msg = str(ctx.exception)
        self.assertIn("projects", msg)
        self.assertIn(c.config_path(), msg)

    def test_specs_missing_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg().specs_root()

    def test_absolute_roots_kept(self):
        c = _cfg(projects="/p", specs="/s")
        self.assertEqual(c.projects_root(), "/p")
        self.assertEqual(c.specs_root(), "/s")

    def test_tilde_expanded_against_home(self):
        self.assertEqual(_cfg(projects="~/p").projects_root(), os.path.join(HOME, "p"))

    def test_relative_joined_to_home(self):
        self.assertEqual(_cfg(projects="rel/p").projects_root(), os.path.join(HOME, "rel/p"))


class TestBranchPrefix(unittest.TestCase):
    def test_missing_key_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().branch_prefix()

    def test_config_value_read(self):
        self.assertEqual(_cfg(branch_prefix="wip").branch_prefix(), "wip")


class TestMaxAgents(unittest.TestCase):
    def test_missing_key_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().max_agents()

    def test_config_value_read(self):
        self.assertEqual(_cfg(max_agents="6").max_agents(), 6)

    def test_env_override_wins(self):
        self.assertEqual(_cfg({"GRID_MAX_AGENTS": "2"}, max_agents="6").max_agents(), 2)

    def test_env_override_without_config_key(self):
        self.assertEqual(_cfg({"GRID_MAX_AGENTS": "7"}).max_agents(), 7)

    def test_malformed_config_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg(max_agents="nope").max_agents()

    def test_malformed_env_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg({"GRID_MAX_AGENTS": "lots"}).max_agents()


class TestTunables(unittest.TestCase):
    def _full_cfg(self, environ=None):
        return _cfg(
            environ,
            worktree_retries="6",
            worktree_retry_sleep="0.25",
            max_boot_seconds="120",
            poll_seconds="5",
            worker_history="20",
            editor="vi",
        )

    def test_values_from_config(self):
        c = self._full_cfg()
        self.assertEqual(c.worktree_retries(), 6)
        self.assertEqual(c.worktree_retry_sleep(), 0.25)
        self.assertEqual(c.max_boot_seconds(), 120)
        self.assertEqual(c.poll_seconds(), 5)
        self.assertEqual(c.worker_history(), 20)
        self.assertEqual(c.editor(), "vi")

    def test_missing_tunable_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().worktree_retries()
        with self.assertRaises(ConfigError):
            _cfg().poll_seconds()
        with self.assertRaises(ConfigError):
            _cfg().editor()

    def test_env_overrides(self):
        c = self._full_cfg({"GRID_WORKTREE_RETRIES": "3", "GRID_POLL_SECONDS": "1",
                            "EDITOR": "nano"})
        self.assertEqual(c.worktree_retries(), 3)
        self.assertEqual(c.poll_seconds(), 1)
        self.assertEqual(c.editor(), "nano")

    def test_env_override_without_config_key(self):
        self.assertEqual(_cfg({"GRID_WORKER_HISTORY": "10"}).worker_history(), 10)
        self.assertEqual(_cfg({"EDITOR": "emacs"}).editor(), "emacs")

    def test_malformed_tunable_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg({"GRID_POLL_SECONDS": "soon"}).poll_seconds()


class TestEnsureConfig(unittest.TestCase):
    def test_creates_all_keys_when_absent(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        c = Config(environ={"GRID_CONFIG": p})
        result = c.ensure_config()
        self.assertTrue(result)
        text = Path(p).read_text()
        self.assertIn("max-agents: 5", text)
        self.assertIn("branch-prefix: feat", text)
        self.assertIn("editor: vi", text)
        self.assertIn("worktree-retry-sleep: 0.25", text)
        self.assertIn("~/workspace/projects", text)
        self.assertIn("retro-interval-days: 7", text)
        self.assertIn("retro-min-epics: 3", text)

    def test_tops_up_missing_keys_in_existing_config(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        Path(p).write_text("projects: /p\nspecs: /s\n")
        c = Config(environ={"GRID_CONFIG": p})
        result = c.ensure_config()
        self.assertTrue(result)
        text = Path(p).read_text()
        self.assertIn("projects: /p", text)
        self.assertIn("max-agents: 5", text)
        self.assertIn("editor: vi", text)

    def test_topup_leaves_existing_values_untouched(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        Path(p).write_text("projects: /p\nspecs: /s\nmax-agents: 8\n")
        c = Config(environ={"GRID_CONFIG": p})
        c.ensure_config()
        cfg = c.load_config()
        self.assertEqual(cfg["max-agents"], "8")

    def test_noop_returns_false_when_all_keys_present(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        all_keys = (
            "projects: /p\nspecs: /s\nbranch-prefix: feat\nmax-agents: 5\n"
            "worktree-retries: 6\nworktree-retry-sleep: 0.25\nmax-boot-seconds: 120\n"
            "poll-seconds: 5\nworker-history: 20\neditor: vi\n"
            "retro-interval-days: 7\nretro-min-epics: 3\n"
        )
        Path(p).write_text(all_keys)
        c = Config(environ={"GRID_CONFIG": p})
        result = c.ensure_config()
        self.assertFalse(result)


class TestSpawnProtocol(unittest.TestCase):
    def test_spawn_id_absent_is_none(self):
        self.assertIsNone(_cfg().spawn_id())

    def test_spawn_id_and_cmd_read_from_env(self):
        c = _cfg({"GRID_SPAWNID": "abc123", "GRID_SPAWN_CMD": "echo hi"})
        self.assertEqual(c.spawn_id(), "abc123")
        self.assertEqual(c.spawn_cmd(), "echo hi")


class TestRetroCadenceConfig(unittest.TestCase):
    def test_missing_key_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().retro_interval_days()
        with self.assertRaises(ConfigError):
            _cfg().retro_min_epics()

    def test_config_values_read(self):
        self.assertEqual(_cfg(retro_interval_days="7").retro_interval_days(), 7)
        self.assertEqual(_cfg(retro_min_epics="3").retro_min_epics(), 3)
        self.assertEqual(_cfg(retro_interval_days="14").retro_interval_days(), 14)
        self.assertEqual(_cfg(retro_min_epics="5").retro_min_epics(), 5)

    def test_env_override_wins(self):
        self.assertEqual(
            _cfg({"GRID_RETRO_INTERVAL_DAYS": "21"}, retro_interval_days="14").retro_interval_days(), 21)
        self.assertEqual(
            _cfg({"GRID_RETRO_MIN_EPICS": "10"}, retro_min_epics="5").retro_min_epics(), 10)

    def test_env_override_without_config_key(self):
        self.assertEqual(_cfg({"GRID_RETRO_INTERVAL_DAYS": "7"}).retro_interval_days(), 7)
        self.assertEqual(_cfg({"GRID_RETRO_MIN_EPICS": "3"}).retro_min_epics(), 3)

    def test_malformed_config_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg(retro_interval_days="weekly").retro_interval_days()
        with self.assertRaises(ConfigError):
            _cfg(retro_min_epics="many").retro_min_epics()


class TestGridRootAndEnv(unittest.TestCase):
    def test_grid_root_override(self):
        self.assertEqual(_cfg({"GRID_ROOT_OVERRIDE": "/tmp/grid"}).grid_root(), "/tmp/grid")

    def test_base_env_is_a_copy(self):
        c = _cfg({"FOO": "bar"})
        e = c.base_env()
        self.assertEqual(e["FOO"], "bar")
        e["FOO"] = "mutated"
        self.assertEqual(c.base_env()["FOO"], "bar")


if __name__ == "__main__":
    unittest.main()
