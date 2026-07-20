import os
import tempfile
import unittest
from pathlib import Path

from lightcycle.config import _SEED_KEYS, Config, ConfigError

HOME = os.path.expanduser("~")


def _cfg(environ=None, **filevals):
    env = dict(environ or {})
    if filevals:
        p = os.path.join(tempfile.mkdtemp(), "config")
        Path(p).write_text(
            "".join("%s: %s\n" % (k.replace("_", "-"), v) for k, v in filevals.items())
        )
        env["LC_CONFIG"] = p
    else:
        env.setdefault("LC_CONFIG", os.path.join(tempfile.mkdtemp(), "absent"))
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

    def test_specs_remote_missing_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg().specs_remote()

    def test_specs_remote_config_value_read(self):
        self.assertEqual(
            _cfg(specs_remote="git@github.com:x/specs.git").specs_remote(),
            "git@github.com:x/specs.git",
        )

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


class TestShortcode(unittest.TestCase):
    def test_missing_key_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().shortcode()

    def test_config_value_read(self):
        self.assertEqual(_cfg(shortcode="GRID").shortcode(), "GRID")


class TestMaxAgents(unittest.TestCase):
    def test_missing_key_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().max_agents()

    def test_config_value_read(self):
        self.assertEqual(_cfg(max_agents="6").max_agents(), 6)

    def test_env_override_wins(self):
        self.assertEqual(_cfg({"LC_MAX_AGENTS": "2"}, max_agents="6").max_agents(), 2)

    def test_env_override_without_config_key(self):
        self.assertEqual(_cfg({"LC_MAX_AGENTS": "7"}).max_agents(), 7)

    def test_malformed_config_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg(max_agents="nope").max_agents()

    def test_malformed_env_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg({"LC_MAX_AGENTS": "lots"}).max_agents()


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
        c = self._full_cfg({"LC_WORKTREE_RETRIES": "3", "LC_POLL_SECONDS": "1",
                            "EDITOR": "nano"})
        self.assertEqual(c.worktree_retries(), 3)
        self.assertEqual(c.poll_seconds(), 1)
        self.assertEqual(c.editor(), "nano")

    def test_env_override_without_config_key(self):
        self.assertEqual(_cfg({"LC_WORKER_HISTORY": "10"}).worker_history(), 10)
        self.assertEqual(_cfg({"EDITOR": "emacs"}).editor(), "emacs")

    def test_malformed_tunable_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg({"LC_POLL_SECONDS": "soon"}).poll_seconds()


class TestEnsureConfig(unittest.TestCase):
    def test_creates_all_keys_when_absent(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        c = Config(environ={"LC_CONFIG": p})
        result = c.ensure_config()
        self.assertTrue(result)
        text = Path(p).read_text()
        self.assertIn("max-agents: 5", text)
        self.assertIn("branch-prefix: feat", text)
        self.assertIn("shortcode: PROJ", text)
        self.assertIn("editor: vi", text)
        self.assertIn("worktree-retry-sleep: 0.25", text)
        self.assertIn("~/workspace/projects", text)
        self.assertIn("retro-interval-reflections: 20", text)
        self.assertIn("specs-remote: git@github.com:you/lightcycle-specs.git", text)
        self.assertIn("backups-dir: ~/.lightcycle-backups", text)
        self.assertIn("backup-interval-minutes: 15", text)
        self.assertIn("backup-retention: 96", text)
        self.assertIn("max-title-length: 72", text)

    def test_tops_up_missing_keys_in_existing_config(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        Path(p).write_text("projects: /p\nspecs: /s\n")
        c = Config(environ={"LC_CONFIG": p})
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
        c = Config(environ={"LC_CONFIG": p})
        c.ensure_config()
        cfg = c.load_config()
        self.assertEqual(cfg["max-agents"], "8")

    def test_noop_returns_false_when_all_keys_present(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        all_keys = (
            "projects: /p\nspecs: /s\nspecs-remote: git@github.com:x/specs.git\n"
            "branch-prefix: feat\nshortcode: PROJ\n"
            "default-origin: lightcycle\n"
            "workflows-remote: git@github.com:kenmclennan/lightcycle-workflows.git\nmax-agents: 5\n"
            "worktree-retries: 6\nworktree-retry-sleep: 0.25\nmax-boot-seconds: 120\n"
            "max-session-seconds: 1800\n"
            "poll-seconds: 5\nworker-history: 20\neditor: vi\n"
            "retro-interval-reflections: 20\n"
            "backups-dir: ~/.lightcycle-backups\nbackup-interval-minutes: 15\n"
            "backup-retention: 96\nworkflow-retention: 5\nmax-title-length: 72\n"
        )
        Path(p).write_text(all_keys)
        c = Config(environ={"LC_CONFIG": p})
        result = c.ensure_config()
        self.assertFalse(result)


class TestReconcileConfig(unittest.TestCase):
    def test_tops_up_missing_keys_in_existing_config(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        Path(p).write_text("projects: /p\nspecs: /s\n")
        c = Config(environ={"LC_CONFIG": p})
        added = c.reconcile_config()
        self.assertIn("max-agents", added)
        self.assertIn("max-title-length", added)
        text = Path(p).read_text()
        self.assertIn("projects: /p", text)
        self.assertIn("max-agents: 5", text)
        self.assertIn("max-title-length: 72", text)

    def test_does_not_create_config_when_absent(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        c = Config(environ={"LC_CONFIG": p})
        added = c.reconcile_config()
        self.assertEqual(added, ())
        self.assertFalse(os.path.exists(p))

    def test_leaves_existing_values_untouched(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        Path(p).write_text("projects: /p\nspecs: /s\nmax-agents: 8\n")
        c = Config(environ={"LC_CONFIG": p})
        c.reconcile_config()
        self.assertEqual(c.load_config()["max-agents"], "8")

    def test_noop_returns_empty_when_all_keys_present(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        c = Config(environ={"LC_CONFIG": p})
        c.ensure_config()
        added = c.reconcile_config()
        self.assertEqual(added, ())


class TestMissingConfigKeys(unittest.TestCase):
    def test_all_seed_keys_present_returns_empty(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        c = Config(environ={"LC_CONFIG": p})
        c.ensure_config()
        self.assertEqual(c.missing_config_keys(), ())

    def test_partial_config_reports_the_rest(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        Path(p).write_text("projects: /p\nspecs: /s\n")
        c = Config(environ={"LC_CONFIG": p})
        missing = c.missing_config_keys()
        self.assertIn("max-agents", missing)
        self.assertIn("default-origin", missing)
        self.assertNotIn("projects", missing)
        self.assertNotIn("specs", missing)

    def test_absent_config_file_reports_every_seed_key(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        c = Config(environ={"LC_CONFIG": p})
        missing = c.missing_config_keys()
        self.assertEqual(set(missing), {k for k, _ in _SEED_KEYS})


class TestMaxTitleLength(unittest.TestCase):
    def test_missing_key_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().max_title_length()

    def test_config_value_read(self):
        self.assertEqual(_cfg(max_title_length="72").max_title_length(), 72)


class TestSpawnProtocol(unittest.TestCase):
    def test_spawn_id_absent_is_none(self):
        self.assertIsNone(_cfg().spawn_id())

    def test_spawn_id_and_cmd_read_from_env(self):
        c = _cfg({"LC_SPAWNID": "abc123", "LC_SPAWN_CMD": "echo hi"})
        self.assertEqual(c.spawn_id(), "abc123")
        self.assertEqual(c.spawn_cmd(), "echo hi")


class TestRetroCadenceConfig(unittest.TestCase):
    def test_missing_key_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().retro_interval_reflections()

    def test_config_value_read(self):
        self.assertEqual(_cfg(retro_interval_reflections="20").retro_interval_reflections(), 20)
        self.assertEqual(_cfg(retro_interval_reflections="5").retro_interval_reflections(), 5)

    def test_env_override_wins(self):
        self.assertEqual(
            _cfg(
                {"LC_RETRO_INTERVAL_REFLECTIONS": "30"}, retro_interval_reflections="20"
            ).retro_interval_reflections(),
            30,
        )

    def test_env_override_without_config_key(self):
        self.assertEqual(
            _cfg({"LC_RETRO_INTERVAL_REFLECTIONS": "20"}).retro_interval_reflections(), 20
        )

    def test_malformed_config_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg(retro_interval_reflections="lots").retro_interval_reflections()

    def test_removed_keys_are_gone(self):
        c = _cfg(retro_interval_reflections="20")
        self.assertFalse(hasattr(c, "retro_interval_items"))
        self.assertFalse(hasattr(c, "retro_interval_days"))
        self.assertFalse(hasattr(c, "retro_min_items"))


class TestBackupConfig(unittest.TestCase):
    def test_missing_keys_raise_naming_the_key(self):
        with self.assertRaises(ConfigError) as ctx:
            _cfg().backups_dir()
        self.assertIn("backups-dir", str(ctx.exception))
        with self.assertRaises(ConfigError) as ctx:
            _cfg().backup_interval_minutes()
        self.assertIn("backup-interval-minutes", str(ctx.exception))
        with self.assertRaises(ConfigError) as ctx:
            _cfg().backup_retention()
        self.assertIn("backup-retention", str(ctx.exception))

    def test_config_values_read(self):
        c = _cfg(backups_dir="/b", backup_interval_minutes="30", backup_retention="10")
        self.assertEqual(c.backups_dir(), "/b")
        self.assertEqual(c.backup_interval_minutes(), 30)
        self.assertEqual(c.backup_retention(), 10)

    def test_malformed_int_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg(backup_interval_minutes="soon").backup_interval_minutes()

    def test_freshly_seeded_config_resolves_backups_dir_outside_data_root(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        c = Config(environ={"LC_HOME": d, "LC_CONFIG": p})
        c.ensure_config()
        self.assertEqual(c.backups_dir(), os.path.join(HOME, ".lightcycle-backups"))
        self.assertEqual(c.backup_interval_minutes(), 15)
        self.assertEqual(c.backup_retention(), 96)
        self.assertFalse(c.backups_dir().startswith(c.data_root() + os.sep))


class TestGridRootAndEnv(unittest.TestCase):
    def test_package_root_ignores_lc_home(self):
        overridden = _cfg({"LC_HOME": "/tmp/grid"}).package_root()
        plain = _cfg().package_root()
        self.assertEqual(overridden, plain)
        self.assertNotEqual(overridden, "/tmp/grid")

    def test_default_data_root_ignores_lc_home(self):
        c = _cfg({"LC_HOME": "/tmp/other"})
        self.assertEqual(c.default_data_root(), os.path.join(HOME, ".lightcycle"))

    def test_data_root_matches_default_when_unset(self):
        self.assertEqual(_cfg().data_root(), _cfg().default_data_root())

    def test_base_env_is_a_copy(self):
        c = _cfg({"FOO": "bar"})
        e = c.base_env()
        self.assertEqual(e["FOO"], "bar")
        e["FOO"] = "mutated"
        self.assertEqual(c.base_env()["FOO"], "bar")


def test_lc_root_override_is_no_longer_read():
    cfg = Config(environ={"LC_ROOT_OVERRIDE": "/should/be/ignored"})
    assert cfg.data_root() != "/should/be/ignored"
    assert cfg.engine_root() != "/should/be/ignored"


def test_legacy_grid_config_is_no_longer_read(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    grid = tmp_path / ".grid"
    grid.mkdir()
    (grid / "config").write_text("shortcode: LEGACY\n")
    new_home = tmp_path / ".lightcycle"
    cfg = Config(environ={"LC_HOME": str(new_home)})
    assert cfg.config_path() == os.path.join(str(new_home), "config")
    assert not hasattr(cfg, "legacy_data_root")
    assert not hasattr(cfg, "legacy_config_path")


if __name__ == "__main__":
    unittest.main()
