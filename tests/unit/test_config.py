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
    def test_default(self):
        self.assertEqual(_cfg().branch_prefix(), "feat")

    def test_hyphen_key_override(self):
        self.assertEqual(_cfg(branch_prefix="wip").branch_prefix(), "wip")


class TestMaxAgents(unittest.TestCase):
    def test_default(self):
        self.assertEqual(_cfg().max_agents(), 4)

    def test_config_override(self):
        self.assertEqual(_cfg(max_agents="6").max_agents(), 6)

    def test_env_override_wins(self):
        self.assertEqual(_cfg({"GRID_MAX_AGENTS": "2"}, max_agents="6").max_agents(), 2)

    def test_malformed_config_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg(max_agents="nope").max_agents()

    def test_malformed_env_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg({"GRID_MAX_AGENTS": "lots"}).max_agents()


class TestTunables(unittest.TestCase):
    def test_explicit_defaults(self):
        c = _cfg()
        self.assertEqual(c.worktree_retries(), 6)
        self.assertEqual(c.worktree_retry_sleep(), 0.25)
        self.assertEqual(c.max_boot_seconds(), 120)
        self.assertEqual(c.poll_seconds(), 5)
        self.assertEqual(c.worker_history(), 20)
        self.assertEqual(c.editor(), "vi")

    def test_env_overrides(self):
        c = _cfg({"GRID_WORKTREE_RETRIES": "3", "GRID_POLL_SECONDS": "1", "EDITOR": "nano"})
        self.assertEqual(c.worktree_retries(), 3)
        self.assertEqual(c.poll_seconds(), 1)
        self.assertEqual(c.editor(), "nano")

    def test_malformed_tunable_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg({"GRID_POLL_SECONDS": "soon"}).poll_seconds()


class TestSpawnProtocol(unittest.TestCase):
    def test_spawn_id_absent_is_none(self):
        self.assertIsNone(_cfg().spawn_id())

    def test_spawn_id_and_cmd_read_from_env(self):
        c = _cfg({"GRID_SPAWNID": "abc123", "GRID_SPAWN_CMD": "echo hi"})
        self.assertEqual(c.spawn_id(), "abc123")
        self.assertEqual(c.spawn_cmd(), "echo hi")


class TestRetroCadenceConfig(unittest.TestCase):
    def test_defaults(self):
        c = _cfg()
        self.assertEqual(c.retro_interval_days(), 7)
        self.assertEqual(c.retro_min_epics(), 3)

    def test_config_file_override(self):
        self.assertEqual(_cfg(retro_interval_days="14").retro_interval_days(), 14)
        self.assertEqual(_cfg(retro_min_epics="5").retro_min_epics(), 5)

    def test_env_override_wins(self):
        self.assertEqual(
            _cfg({"GRID_RETRO_INTERVAL_DAYS": "21"}, retro_interval_days="14").retro_interval_days(), 21)
        self.assertEqual(
            _cfg({"GRID_RETRO_MIN_EPICS": "10"}, retro_min_epics="5").retro_min_epics(), 10)

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
