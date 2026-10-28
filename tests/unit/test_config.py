import os
import tempfile
import unittest
from pathlib import Path

from lightcycle.config import _SEED_KEYS, Config, ConfigError, ConfigValueError
from lightcycle.domain.pool import ModelRates
from lightcycle.domain.schedule.guards import guard_names



def _home():
    return os.path.expanduser("~")


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

    def test_absolute_roots_kept(self):
        c = _cfg(projects="/p")
        self.assertEqual(c.projects_root(), "/p")

    def test_tilde_expanded_against_home(self):
        self.assertEqual(_cfg(projects="~/p").projects_root(), os.path.join(_home(), "p"))

    def test_relative_joined_to_home(self):
        self.assertEqual(_cfg(projects="rel/p").projects_root(), os.path.join(_home(), "rel/p"))


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
        self.assertEqual(_cfg({"LC_MAX_AGENTS": "2"}, max_agents="6").max_agents(), 2)

    def test_env_override_without_config_key(self):
        self.assertEqual(_cfg({"LC_MAX_AGENTS": "7"}).max_agents(), 7)

    def test_malformed_config_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg(max_agents="nope").max_agents()

    def test_malformed_env_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg({"LC_MAX_AGENTS": "lots"}).max_agents()

    def test_zero_is_accepted(self):
        self.assertEqual(_cfg(max_agents="0").max_agents(), 0)

    def test_negative_is_refused_via_config_naming_key_and_value(self):
        with self.assertRaises(ConfigError) as ctx:
            _cfg(max_agents="-1").max_agents()
        msg = str(ctx.exception)
        self.assertIn("max-agents", msg)
        self.assertIn("-1", msg)

    def test_negative_is_refused_via_env(self):
        with self.assertRaises(ConfigError) as ctx:
            _cfg({"LC_MAX_AGENTS": "-1"}).max_agents()
        msg = str(ctx.exception)
        self.assertIn("max-agents", msg)
        self.assertIn("-1", msg)

    def test_negative_is_a_value_error_not_a_missing_key(self):
        with self.assertRaises(ConfigValueError):
            _cfg(max_agents="-1").max_agents()

    def test_malformed_is_a_value_error_not_a_missing_key(self):
        with self.assertRaises(ConfigValueError):
            _cfg(max_agents="nope").max_agents()

    def test_missing_key_is_not_a_value_error(self):
        with self.assertRaises(ConfigError) as ctx:
            _cfg().max_agents()
        self.assertNotIsInstance(ctx.exception, ConfigValueError)


class TestTunables(unittest.TestCase):
    def _full_cfg(self, environ=None):
        return _cfg(
            environ,
            worktree_retries="6",
            worktree_retry_sleep="0.25",
            max_boot_seconds="120",
            stall_seconds="1800",
            probe_cooldown_seconds="1800",
            poll_seconds="5",
            worker_history="20",
            editor="vi",
            spin_cap="3",
        )

    def test_values_from_config(self):
        c = self._full_cfg()
        self.assertEqual(c.worktree_retries(), 6)
        self.assertEqual(c.worktree_retry_sleep(), 0.25)
        self.assertEqual(c.max_boot_seconds(), 120)
        self.assertEqual(c.stall_seconds(), 1800)
        self.assertEqual(c.probe_cooldown_seconds(), 1800)
        self.assertEqual(c.poll_seconds(), 5)
        self.assertEqual(c.worker_history(), 20)
        self.assertEqual(c.editor(), "vi")
        self.assertEqual(c.spin_cap(), 3)

    def test_github_poll_seconds_is_required_and_named_when_missing(self):
        self.assertEqual(_cfg(github_poll_seconds="60").github_poll_seconds(), 60)
        with self.assertRaises(ConfigError) as ctx:
            _cfg().github_poll_seconds()
        self.assertIn("github-poll-seconds", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, ConfigValueError)

    def test_github_poll_seconds_rejects_a_non_integer(self):
        with self.assertRaises(ConfigValueError):
            _cfg(github_poll_seconds="soon").github_poll_seconds()

    def test_github_poll_seconds_env_override(self):
        c = _cfg({"LC_GITHUB_POLL_SECONDS": "30"})
        self.assertEqual(c.github_poll_seconds(), 30)

    def test_github_view_refresh_polls_is_required_and_named_when_missing(self):
        self.assertEqual(_cfg(github_view_refresh_polls="10").github_view_refresh_polls(), 10)
        with self.assertRaises(ConfigError) as ctx:
            _cfg().github_view_refresh_polls()
        self.assertIn("github-view-refresh-polls", str(ctx.exception))

    def test_github_view_refresh_polls_rejects_a_non_integer_and_zero(self):
        with self.assertRaises(ConfigValueError):
            _cfg(github_view_refresh_polls="often").github_view_refresh_polls()
        with self.assertRaises(ConfigValueError):
            _cfg(github_view_refresh_polls="0").github_view_refresh_polls()

    def test_github_view_refresh_polls_env_override(self):
        c = _cfg({"LC_GITHUB_VIEW_REFRESH_POLLS": "3"})
        self.assertEqual(c.github_view_refresh_polls(), 3)

    def test_missing_tunable_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().worktree_retries()
        with self.assertRaises(ConfigError):
            _cfg().poll_seconds()
        with self.assertRaises(ConfigError):
            _cfg().editor()
        with self.assertRaises(ConfigError):
            _cfg().stall_seconds()
        with self.assertRaises(ConfigError):
            _cfg().probe_cooldown_seconds()
        with self.assertRaises(ConfigError):
            _cfg().spin_cap()

    def test_env_overrides(self):
        c = self._full_cfg({"LC_WORKTREE_RETRIES": "3", "LC_POLL_SECONDS": "1",
                            "EDITOR": "nano", "LC_STALL_SECONDS": "900",
                            "LC_PROBE_COOLDOWN_SECONDS": "900", "LC_SPIN_CAP": "5"})
        self.assertEqual(c.worktree_retries(), 3)
        self.assertEqual(c.poll_seconds(), 1)
        self.assertEqual(c.editor(), "nano")
        self.assertEqual(c.stall_seconds(), 900)
        self.assertEqual(c.probe_cooldown_seconds(), 900)
        self.assertEqual(c.spin_cap(), 5)

    def test_env_override_without_config_key(self):
        self.assertEqual(_cfg({"LC_WORKER_HISTORY": "10"}).worker_history(), 10)
        self.assertEqual(_cfg({"EDITOR": "emacs"}).editor(), "emacs")
        self.assertEqual(_cfg({"LC_STALL_SECONDS": "900"}).stall_seconds(), 900)
        self.assertEqual(
            _cfg({"LC_PROBE_COOLDOWN_SECONDS": "900"}).probe_cooldown_seconds(), 900
        )

    def test_malformed_tunable_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg({"LC_POLL_SECONDS": "soon"}).poll_seconds()
        with self.assertRaises(ConfigError):
            _cfg({"LC_STALL_SECONDS": "soon"}).stall_seconds()
        with self.assertRaises(ConfigError):
            _cfg({"LC_PROBE_COOLDOWN_SECONDS": "soon"}).probe_cooldown_seconds()

    def test_seconds_getters_accept_zero(self):
        self.assertEqual(_cfg(max_boot_seconds="0").max_boot_seconds(), 0)
        self.assertEqual(_cfg(max_session_seconds="0").max_session_seconds(), 0)
        self.assertEqual(_cfg(stall_seconds="0").stall_seconds(), 0)
        self.assertEqual(_cfg(probe_cooldown_seconds="0").probe_cooldown_seconds(), 0)
        self.assertEqual(_cfg(shutdown_grace_seconds="0").shutdown_grace_seconds(), 0)

    def test_seconds_getters_refuse_negative_via_config(self):
        cases = (
            ("max_boot_seconds", "max_boot_seconds", "max-boot-seconds"),
            ("max_session_seconds", "max_session_seconds", "max-session-seconds"),
            ("stall_seconds", "stall_seconds", "stall-seconds"),
            ("probe_cooldown_seconds", "probe_cooldown_seconds", "probe-cooldown-seconds"),
            ("shutdown_grace_seconds", "shutdown_grace_seconds", "shutdown-grace-seconds"),
        )
        for filekey, getter, key in cases:
            with self.assertRaises(ConfigError) as ctx:
                getattr(_cfg(**{filekey: "-1"}), getter)()
            self.assertIn(key, str(ctx.exception), key)

    def test_seconds_getters_refuse_negative_via_env(self):
        cases = (
            ("LC_MAX_BOOT_SECONDS", "max_boot_seconds", "max-boot-seconds"),
            ("LC_MAX_SESSION_SECONDS", "max_session_seconds", "max-session-seconds"),
            ("LC_STALL_SECONDS", "stall_seconds", "stall-seconds"),
            ("LC_PROBE_COOLDOWN_SECONDS", "probe_cooldown_seconds", "probe-cooldown-seconds"),
            ("LC_SHUTDOWN_GRACE_SECONDS", "shutdown_grace_seconds", "shutdown-grace-seconds"),
        )
        for envvar, getter, key in cases:
            with self.assertRaises(ConfigError) as ctx:
                getattr(_cfg({envvar: "-1"}), getter)()
            self.assertIn(key, str(ctx.exception), key)


class TestGuidanceBudgetConfig(unittest.TestCase):
    def test_seeded_default_is_8192(self):
        seeds = dict(_SEED_KEYS)
        self.assertEqual(seeds["guidance-budget-bytes"], "8192")
        self.assertEqual(_cfg(guidance_budget_bytes=seeds["guidance-budget-bytes"]).guidance_budget_bytes(), 8192)

    def test_env_override_wins(self):
        c = _cfg({"LC_GUIDANCE_BUDGET_BYTES": "10"}, guidance_budget_bytes="6144")
        self.assertEqual(c.guidance_budget_bytes(), 10)

    def test_zero_is_allowed_and_negative_is_refused(self):
        self.assertEqual(_cfg(guidance_budget_bytes="0").guidance_budget_bytes(), 0)
        with self.assertRaises(ConfigError) as ctx:
            _cfg(guidance_budget_bytes="-1").guidance_budget_bytes()
        self.assertIn("guidance-budget-bytes", str(ctx.exception))
        with self.assertRaises(ConfigError):
            _cfg({"LC_GUIDANCE_BUDGET_BYTES": "-1"}).guidance_budget_bytes()


class TestMemoryConfig(unittest.TestCase):
    def test_seeded_default_is_the_calibrated_reserve_fraction(self):
        seeds = dict(_SEED_KEYS)
        c = _cfg(memory_reserve_fraction=seeds["memory-reserve-fraction"])
        self.assertEqual(c.memory_reserve_fraction(), 0.65)

    def test_gate_seeds_carry_no_suspend_or_resume_pressure(self):
        seeds = {k for k, _ in _SEED_KEYS}
        self.assertNotIn("suspend-pressure", seeds)
        self.assertNotIn("resume-pressure", seeds)

    def test_missing_key_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().memory_reserve_fraction()

    def test_env_override_wins(self):
        c = _cfg({"LC_MEMORY_RESERVE_FRACTION": "0.1"}, memory_reserve_fraction="0.65")
        self.assertEqual(c.memory_reserve_fraction(), 0.1)

    def test_env_override_without_config_key(self):
        self.assertEqual(
            _cfg({"LC_MEMORY_RESERVE_FRACTION": "0.4"}).memory_reserve_fraction(), 0.4
        )

    def test_malformed_config_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg(memory_reserve_fraction="nope").memory_reserve_fraction()

    def test_memory_reserve_fraction_accepts_both_boundary_values(self):
        self.assertEqual(
            _cfg(memory_reserve_fraction="0.0").memory_reserve_fraction(), 0.0
        )
        self.assertEqual(
            _cfg(memory_reserve_fraction="1.0").memory_reserve_fraction(), 1.0
        )

    def test_memory_reserve_fraction_out_of_range_raises_naming_key_and_value(self):
        for raw in ("-0.1", "1.1"):
            with self.assertRaises(ConfigError) as ctx:
                _cfg(memory_reserve_fraction=raw).memory_reserve_fraction()
            msg = str(ctx.exception)
            self.assertIn("memory-reserve-fraction", msg)
            self.assertIn(raw, msg)

    def test_memory_reserve_fraction_out_of_range_via_env_raises(self):
        with self.assertRaises(ConfigError) as ctx:
            _cfg({"LC_MEMORY_RESERVE_FRACTION": "1.1"}).memory_reserve_fraction()
        msg = str(ctx.exception)
        self.assertIn("memory-reserve-fraction", msg)
        self.assertIn("1.1", msg)

    def test_a_config_still_carrying_the_removed_pressure_keys_loads_and_reports_them_obsolete(self):
        c = _cfg(
            memory_reserve_fraction="0.65", suspend_pressure="0.85", resume_pressure="0.70",
        )
        self.assertEqual(c.memory_reserve_fraction(), 0.65)
        self.assertEqual(c.obsolete_config_keys(), ("suspend-pressure", "resume-pressure"))
        self.assertFalse(hasattr(c, "suspend_pressure"))
        self.assertFalse(hasattr(c, "resume_pressure"))


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
        self.assertNotIn("shortcode: PROJ", text)
        self.assertIn("editor: vi", text)
        self.assertIn("worktree-retry-sleep: 0.25", text)
        self.assertIn("~/workspace/projects", text)
        self.assertIn("workflows-remote: \n", text)
        self.assertIn("backups-dir: ~/.lightcycle-backups", text)
        self.assertIn("backup-interval-minutes: 15", text)
        self.assertIn("backup-retention: 96", text)
        self.assertIn("max-title-length: 72", text)

    def test_a_fresh_config_seeds_the_ratchet_sweep_schedule_with_a_guard_the_engine_has(self):
        p = os.path.join(tempfile.mkdtemp(), "config")
        c = Config(environ={"LC_CONFIG": p})
        c.ensure_config()
        block = c.schedule_blocks()["ratchet-sweep"]
        self.assertEqual(
            (block["enabled"], block["workflow"], block["project"], block["shortcode"],
             block["cron"], block["guard"]),
            ("true", "lightcycle/ratchet-sweep", "guidance", "AUD", "0 9 * * 1", "repos-active"))
        self.assertIn(block["guard"], guard_names())

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
        all_keys = "".join("%s: %s\n" % (k, v) for k, v in _SEED_KEYS)
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

    def test_seeds_missing_path_keys_from_registered_projects(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        Path(p).write_text("projects: /p\n")
        c = Config(environ={"LC_CONFIG": p})
        c.reconcile_config({"guidance-path": "/elsewhere/guidance", "specs-path": "/elsewhere/specs"})
        self.assertEqual(c.load_config()["guidance-path"], "/elsewhere/guidance")
        self.assertEqual(c.load_config()["specs-path"], "/elsewhere/specs")

    def test_registered_path_beats_scratch_home_seed(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        Path(p).write_text("projects: /p\n")
        c = Config(environ={"LC_CONFIG": p, "LC_HOME": d})
        c.reconcile_config({"guidance-path": "/elsewhere/guidance"})
        self.assertEqual(c.load_config()["guidance-path"], "/elsewhere/guidance")
        self.assertEqual(c.load_config()["specs-path"], os.path.join(d, "specs"))

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


class TestObsoleteConfigKeys(unittest.TestCase):
    def test_freshly_seeded_config_returns_empty(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        c = Config(environ={"LC_CONFIG": p})
        c.ensure_config()
        self.assertEqual(c.obsolete_config_keys(), ())

    def test_mixed_known_and_unknown_keys_reports_only_unknown(self):
        c = _cfg(projects="/p", retro_interval_items="5")
        obsolete = c.obsolete_config_keys()
        self.assertEqual(obsolete, ("retro-interval-items",))
        self.assertNotIn("projects", obsolete)

    def test_only_unknown_keys_reports_all_of_them_and_missing_still_reports_seed_keys(self):
        c = _cfg(retro_interval_items="5", old_flag="x")
        self.assertEqual(c.obsolete_config_keys(), ("retro-interval-items", "old-flag"))
        self.assertEqual(set(c.missing_config_keys()), {k for k, _ in _SEED_KEYS})


class TestRetiredGlobalShortcodeKey(unittest.TestCase):
    def test_a_freshly_seeded_config_has_no_shortcode_key_and_reports_nothing_obsolete(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        c = Config(environ={"LC_CONFIG": p})
        c.ensure_config()
        self.assertNotIn("shortcode", {k for k, _ in _SEED_KEYS})
        self.assertNotRegex(Path(p).read_text(), r"(?m)^shortcode:")
        self.assertEqual(c.obsolete_config_keys(), ())

    def test_a_file_still_carrying_shortcode_loads_and_is_reported_obsolete(self):
        c = _cfg(shortcode="PROJ")
        self.assertEqual(c.obsolete_config_keys(), ("shortcode",))
        self.assertFalse(hasattr(c, "shortcode"))

    def test_resolved_settings_has_no_shortcode_entry(self):
        self.assertNotIn("shortcode", {s.key for s in _cfg().resolved_settings()})


class TestRenamedShortcodeKey(unittest.TestCase):
    def test_a_file_still_carrying_internal_shortcode_is_reported_obsolete(self):
        c = _cfg(internal_shortcode="AUD")
        self.assertIn("internal-shortcode", c.obsolete_config_keys())

    def test_new_shortcode_keys_are_seeded_with_their_defaults(self):
        seeds = dict(_SEED_KEYS)
        self.assertEqual(seeds["audit-shortcode"], "AUD")
        self.assertNotIn("summary-shortcode", seeds)


class TestTrustedAuthors(unittest.TestCase):
    def test_the_value_is_split_on_whitespace_and_casefolded(self):
        c = _cfg(trusted_authors="Alice  bob\tCarol")
        self.assertEqual(c.trusted_authors(), frozenset({"alice", "bob", "carol"}))

    def test_a_blank_or_missing_key_raises_and_reports_unset(self):
        for c in (_cfg(trusted_authors=""), _cfg()):
            with self.assertRaises(ConfigError):
                c.trusted_authors()
            entry = next(s for s in c.resolved_settings() if s.key == "trusted-authors")
            self.assertEqual(entry.state, "unset")

    def test_seeding_writes_a_blank_key_and_never_overwrites_a_value(self):
        c = _cfg(trusted_authors="")
        self.assertTrue(c.seed_trusted_authors("ken"))
        self.assertEqual(c.trusted_authors(), frozenset({"ken"}))
        self.assertFalse(c.seed_trusted_authors("someone-else"))
        self.assertEqual(c.trusted_authors(), frozenset({"ken"}))

    def test_seeding_a_config_without_the_key_appends_it(self):
        c = _cfg(projects="/p")
        self.assertTrue(c.seed_trusted_authors("ken"))
        self.assertEqual(c.trusted_authors(), frozenset({"ken"}))

    def test_reconcile_appends_the_key_blank_to_an_existing_config(self):
        c = _cfg(projects="/p")
        self.assertIn("trusted-authors", c.reconcile_config())
        with self.assertRaises(ConfigError):
            c.trusted_authors()

    def test_the_guidance_shortcode_is_seeded_gdn_with_an_env_override(self):
        self.assertEqual(dict(_SEED_KEYS)["guidance-shortcode"], "GDN")
        self.assertEqual(_cfg(guidance_shortcode="GDN").guidance_shortcode(), "GDN")
        env = _cfg(environ={"LC_GUIDANCE_SHORTCODE": "ZZZ"})
        self.assertEqual(env.guidance_shortcode(), "ZZZ")
        with self.assertRaises(ConfigError):
            _cfg().guidance_shortcode()

    def test_the_held_comment_shortcode_is_seeded_hld_with_an_env_override(self):
        self.assertEqual(dict(_SEED_KEYS)["held-comment-shortcode"], "HLD")
        self.assertEqual(_cfg(held_comment_shortcode="HLD").held_comment_shortcode(), "HLD")
        env = _cfg(environ={"LC_HELD_COMMENT_SHORTCODE": "ZZZ"})
        self.assertEqual(env.held_comment_shortcode(), "ZZZ")


class TestMaxTitleLength(unittest.TestCase):
    def test_missing_key_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().max_title_length()

    def test_config_value_read(self):
        self.assertEqual(_cfg(max_title_length="72").max_title_length(), 72)


class TestWorkflowRetention(unittest.TestCase):
    def test_config_value_read(self):
        self.assertEqual(_cfg(workflow_retention="3").workflow_retention(), 3)

    def test_one_is_the_minimum(self):
        self.assertEqual(_cfg(workflow_retention="1").workflow_retention(), 1)

    def test_zero_is_refused(self):
        with self.assertRaises(ConfigValueError):
            _cfg(workflow_retention="0").workflow_retention()

    def test_negative_is_refused(self):
        with self.assertRaises(ConfigValueError):
            _cfg(workflow_retention="-2").workflow_retention()


class TestSpawnProtocol(unittest.TestCase):
    def test_spawn_id_absent_is_none(self):
        self.assertIsNone(_cfg().spawn_id())

    def test_spawn_id_and_cmd_read_from_env(self):
        c = _cfg({"LC_SPAWNID": "abc123", "LC_SPAWN_CMD": "echo hi"})
        self.assertEqual(c.spawn_id(), "abc123")
        self.assertEqual(c.spawn_cmd(), "echo hi")


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

    def test_guidance_fetch_minutes_is_seeded_at_five(self):
        d = tempfile.mkdtemp()
        c = Config(environ={"LC_HOME": d, "LC_CONFIG": os.path.join(d, "config")})
        c.ensure_config()
        self.assertEqual(c.guidance_fetch_minutes(), 5)

    def test_guidance_fetch_minutes_missing_names_the_key(self):
        with self.assertRaises(ConfigError) as ctx:
            _cfg().guidance_fetch_minutes()
        self.assertIn("guidance-fetch-minutes", str(ctx.exception))

    def test_guidance_fetch_minutes_non_integer_raises(self):
        with self.assertRaises(ConfigError):
            _cfg(guidance_fetch_minutes="soon").guidance_fetch_minutes()

    def test_malformed_int_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg(backup_interval_minutes="soon").backup_interval_minutes()

    def test_freshly_seeded_config_resolves_backups_dir_outside_data_root(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        c = Config(environ={"LC_HOME": d, "LC_CONFIG": p})
        c.ensure_config()
        self.assertEqual(c.backups_dir(), os.path.join(_home(), ".lightcycle-backups"))
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
        self.assertEqual(c.default_data_root(), os.path.join(_home(), ".lightcycle"))

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


class TestPersonalOrigin(unittest.TestCase):
    def test_returns_none_when_absent(self):
        self.assertIsNone(_cfg().personal_origin())

    def test_returns_none_when_seeded_empty(self):
        self.assertIsNone(_cfg(personal_origin="").personal_origin())

    def test_set_replaces_seeded_empty_key_in_place_leaving_others_untouched(self):
        c = _cfg(branch_prefix="wip", personal_origin="")
        c.set_personal_origin("acme")
        self.assertEqual(c.personal_origin(), "acme")
        self.assertEqual(c.branch_prefix(), "wip")

    def test_set_again_with_a_different_name_overwrites(self):
        c = _cfg(branch_prefix="wip", personal_origin="")
        c.set_personal_origin("acme")
        c.set_personal_origin("other")
        self.assertEqual(c.personal_origin(), "other")


class TestContextArtifactTypes(unittest.TestCase):
    def test_unset_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().context_artifact_types()

    def test_blank_raises(self):
        with self.assertRaises(ConfigError):
            _cfg(context_artifact_types="").context_artifact_types()

    def test_returns_declared_types_when_set(self):
        c = _cfg(context_artifact_types="spec brief")
        self.assertEqual(c.context_artifact_types(), frozenset({"spec", "brief"}))


class TestContextArtifactProject(unittest.TestCase):
    def test_unset_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().context_artifact_project()

    def test_returns_declared_project(self):
        self.assertEqual(_cfg(context_artifact_project="docs").context_artifact_project(), "docs")


class TestReviewRoundsCap(unittest.TestCase):
    def test_missing_key_raises(self):
        with self.assertRaises(ConfigError):
            _cfg().review_rounds_cap()

    def test_seeded_default_resolves(self):
        self.assertEqual(_cfg(review_rounds_cap="5").review_rounds_cap(), 5)

    def test_env_override_wins(self):
        self.assertEqual(
            _cfg({"LC_REVIEW_ROUNDS_CAP": "8"}, review_rounds_cap="5").review_rounds_cap(), 8
        )

    def test_env_override_without_config_key(self):
        self.assertEqual(_cfg({"LC_REVIEW_ROUNDS_CAP": "3"}).review_rounds_cap(), 3)

    def test_malformed_config_fails_fast(self):
        with self.assertRaises(ConfigError):
            _cfg(review_rounds_cap="lots").review_rounds_cap()


class TestAuditAndSummaryShortcodes(unittest.TestCase):
    def test_missing_keys_raise(self):
        with self.assertRaises(ConfigError):
            _cfg().audit_shortcode()

    def test_seeded_defaults_resolve(self):
        self.assertEqual(_cfg(audit_shortcode="AUD").audit_shortcode(), "AUD")

    def test_env_override_wins(self):
        self.assertEqual(
            _cfg({"LC_AUDIT_SHORTCODE": "ADT"}, audit_shortcode="AUD").audit_shortcode(), "ADT",
        )

    def test_env_override_without_config_key(self):
        self.assertEqual(_cfg({"LC_AUDIT_SHORTCODE": "ADT"}).audit_shortcode(), "ADT")


class TestResolvedSettings(unittest.TestCase):
    def test_freshly_seeded_config_reports_the_seed_text_for_every_key(self):
        c = _cfg()
        c.ensure_config()
        seeds = dict(_SEED_KEYS)
        settings = c.resolved_settings()
        self.assertEqual(len(settings), len(_SEED_KEYS))
        for s in settings:
            self.assertEqual(s.seed, seeds[s.key], s.key)

    def test_workflows_remote_is_seeded_empty_so_it_reports_unset_until_the_user_sets_it(self):
        c = _cfg()
        c.ensure_config()
        settings = {s.key: s for s in c.resolved_settings()}
        s = settings["workflows-remote"]
        self.assertEqual(s.state, "unset")
        self.assertIsNotNone(s.error)

    def test_missing_keys_of_different_shapes_still_report_every_key(self):
        c = _cfg()
        c.ensure_config()
        text = Path(c.config_path()).read_text()
        text = "\n".join(
            line for line in text.splitlines()
            if not line.startswith(("max-agents:", "backups-dir:", "editor:"))
        ) + "\n"
        Path(c.config_path()).write_text(text)
        settings = {s.key: s for s in c.resolved_settings()}
        self.assertEqual(len(settings), len(_SEED_KEYS))
        for key in ("max-agents", "backups-dir", "editor"):
            self.assertEqual(settings[key].state, "unset")
            self.assertIsNotNone(settings[key].error)

    def test_env_override_reports_env_state_and_value(self):
        c = _cfg({"LC_MAX_AGENTS": "9"}, max_agents="5")
        settings = {s.key: s for s in c.resolved_settings()}
        s = settings["max-agents"]
        self.assertEqual(s.state, "env")
        self.assertEqual(s.env_var, "LC_MAX_AGENTS")
        self.assertEqual(s.value, 9)

    def test_editor_env_override_uses_editor_var_not_lc_prefixed(self):
        c = _cfg({"EDITOR": "nano"})
        settings = {s.key: s for s in c.resolved_settings()}
        s = settings["editor"]
        self.assertEqual(s.state, "env")
        self.assertEqual(s.env_var, "EDITOR")
        self.assertEqual(s.value, "nano")

    def test_value_set_in_file_reports_seed_alongside_the_chosen_value(self):
        c = _cfg(max_agents="9")
        settings = {s.key: s for s in c.resolved_settings()}
        s = settings["max-agents"]
        self.assertEqual(s.state, "set")
        self.assertEqual(s.value, 9)
        self.assertEqual(s.seed, "5")

    def test_value_left_at_the_seed_still_reports_the_seed_not_a_provenance_claim(self):
        c = _cfg()
        c.ensure_config()
        settings = {s.key: s for s in c.resolved_settings()}
        s = settings["max-agents"]
        self.assertEqual(s.state, "set")
        self.assertEqual(s.value, 5)
        self.assertEqual(s.seed, "5")

    def test_untouched_personal_origin_reports_its_empty_seed_and_none_value(self):
        c = _cfg()
        c.ensure_config()
        settings = {s.key: s for s in c.resolved_settings()}
        s = settings["personal-origin"]
        self.assertEqual(s.state, "set")
        self.assertEqual(s.seed, "")
        self.assertIsNone(s.value)

    def test_path_keys_at_literal_seed_report_the_raw_seed_text(self):
        c = _cfg()
        c.ensure_config()
        settings = {s.key: s for s in c.resolved_settings()}
        for key in ("projects", "backups-dir"):
            s = settings[key]
            self.assertEqual(s.state, "set", key)
            self.assertTrue(os.path.isabs(s.value), key)
            self.assertFalse(os.path.isabs(s.seed), key)

    def test_out_of_range_value_reports_invalid_not_unset(self):
        c = _cfg(max_agents="-1")
        settings = {s.key: s for s in c.resolved_settings()}
        s = settings["max-agents"]
        self.assertEqual(s.state, "invalid")
        self.assertIn("-1", s.error)
        self.assertIn(">=", s.error)

    def test_malformed_value_reports_invalid_not_unset(self):
        c = _cfg(max_agents="nope")
        settings = {s.key: s for s in c.resolved_settings()}
        s = settings["max-agents"]
        self.assertEqual(s.state, "invalid")
        self.assertIn("nope", s.error)

    def test_genuinely_absent_key_still_reports_unset_not_invalid(self):
        c = _cfg()
        c.ensure_config()
        text = Path(c.config_path()).read_text()
        text = "\n".join(
            line for line in text.splitlines() if not line.startswith("max-agents:")
        ) + "\n"
        Path(c.config_path()).write_text(text)
        settings = {s.key: s for s in c.resolved_settings()}
        s = settings["max-agents"]
        self.assertEqual(s.state, "unset")


_ALL_PRICE_KEYS = dict(
    price_sonnet_input_per_mtok="3.00",
    price_sonnet_output_per_mtok="15.00",
    price_sonnet_cache_write_per_mtok="3.75",
    price_sonnet_cache_read_per_mtok="0.30",
    price_opus_input_per_mtok="6.00",
    price_opus_output_per_mtok="30.00",
    price_opus_cache_write_per_mtok="7.50",
    price_opus_cache_read_per_mtok="0.60",
    price_haiku_input_per_mtok="1.50",
    price_haiku_output_per_mtok="7.50",
    price_haiku_cache_write_per_mtok="1.875",
    price_haiku_cache_read_per_mtok="0.15",
)


class TestUsagePricing(unittest.TestCase):
    def test_returns_sonnet_opus_and_haiku_rates_parsed_as_floats_from_a_config_file_that_sets_them(self):
        c = _cfg(**_ALL_PRICE_KEYS)
        rates = c.usage_pricing()
        self.assertEqual(rates, {
            "sonnet": ModelRates(input=3.00, output=15.00, cache_write=3.75, cache_read=0.30),
            "opus": ModelRates(input=6.00, output=30.00, cache_write=7.50, cache_read=0.60),
            "haiku": ModelRates(input=1.50, output=7.50, cache_write=1.875, cache_read=0.15),
        })

    def test_a_missing_price_key_raises_config_error(self):
        filevals = dict(_ALL_PRICE_KEYS)
        del filevals["price_sonnet_cache_read_per_mtok"]
        c = _cfg(**filevals)
        with self.assertRaises(ConfigError):
            c.usage_pricing()

    def test_a_missing_opus_or_haiku_key_raises_config_error(self):
        for missing in ("price_opus_input_per_mtok", "price_haiku_cache_read_per_mtok"):
            filevals = dict(_ALL_PRICE_KEYS)
            del filevals[missing]
            c = _cfg(**filevals)
            with self.assertRaises(ConfigError):
                c.usage_pricing()

    def test_a_negative_price_key_raises_config_error_naming_it(self):
        for negative_key in _ALL_PRICE_KEYS:
            filevals = dict(_ALL_PRICE_KEYS)
            filevals[negative_key] = "-1"
            c = _cfg(**filevals)
            with self.assertRaises(ConfigError) as ctx:
                c.usage_pricing()
            self.assertIn(negative_key.replace("_", "-"), str(ctx.exception), negative_key)

    def test_all_price_keys_at_zero_resolve_cleanly(self):
        filevals = {k: "0" for k in _ALL_PRICE_KEYS}
        c = _cfg(**filevals)
        rates = c.usage_pricing()
        self.assertEqual(
            rates,
            {
                "sonnet": ModelRates(input=0.0, output=0.0, cache_write=0.0, cache_read=0.0),
                "opus": ModelRates(input=0.0, output=0.0, cache_write=0.0, cache_read=0.0),
                "haiku": ModelRates(input=0.0, output=0.0, cache_write=0.0, cache_read=0.0),
            },
        )


class TestOpusPricing(unittest.TestCase):
    def test_missing_key_raises_config_error(self):
        c = _cfg()
        with self.assertRaises(ConfigError):
            c.price_opus_input_per_mtok()

    def test_reads_value_from_config_file(self):
        c = _cfg(price_opus_input_per_mtok="6.00")
        self.assertEqual(c.price_opus_input_per_mtok(), 6.00)


class TestHaikuPricing(unittest.TestCase):
    def test_missing_key_raises_config_error(self):
        c = _cfg()
        with self.assertRaises(ConfigError):
            c.price_haiku_input_per_mtok()

    def test_reads_value_from_config_file(self):
        c = _cfg(price_haiku_input_per_mtok="1.50")
        self.assertEqual(c.price_haiku_input_per_mtok(), 1.50)


class TestTuiAutostartPool(unittest.TestCase):
    def test_reads_true_and_false_from_the_config_file(self):
        self.assertTrue(_cfg(tui_autostart_pool="true").tui_autostart_pool())
        self.assertFalse(_cfg(tui_autostart_pool="false").tui_autostart_pool())

    def test_accepts_the_documented_spellings_case_insensitively(self):
        for raw in ("TRUE", "Yes", "1", "on"):
            self.assertTrue(_cfg(tui_autostart_pool=raw).tui_autostart_pool(), raw)
        for raw in ("FALSE", "No", "0", "off"):
            self.assertFalse(_cfg(tui_autostart_pool=raw).tui_autostart_pool(), raw)

    def test_a_value_that_is_neither_is_refused_naming_the_key(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(tui_autostart_pool="maybe").tui_autostart_pool()
        self.assertIn("tui-autostart-pool", str(e.exception))
        self.assertIn("maybe", str(e.exception))

    def test_an_unset_value_is_refused_rather_than_defaulted(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(max_agents="5").tui_autostart_pool()
        self.assertIn("tui-autostart-pool", str(e.exception))

    def test_the_env_var_overrides_the_file(self):
        cfg = _cfg(environ={"LC_TUI_AUTOSTART_POOL": "true"}, tui_autostart_pool="false")
        self.assertTrue(cfg.tui_autostart_pool())

    def test_it_is_seeded_false_in_the_default_config(self):
        self.assertEqual(dict(_SEED_KEYS)["tui-autostart-pool"], "false")


class TestTuiMetrics(unittest.TestCase):
    def test_reads_true_and_false_from_the_config_file(self):
        self.assertTrue(_cfg(tui_metrics="true").tui_metrics())
        self.assertFalse(_cfg(tui_metrics="false").tui_metrics())

    def test_accepts_the_documented_spellings_case_insensitively(self):
        for raw in ("TRUE", "Yes", "1", "on"):
            self.assertTrue(_cfg(tui_metrics=raw).tui_metrics(), raw)
        for raw in ("FALSE", "No", "0", "off"):
            self.assertFalse(_cfg(tui_metrics=raw).tui_metrics(), raw)

    def test_a_value_that_is_neither_is_refused_naming_the_key(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(tui_metrics="maybe").tui_metrics()
        self.assertIn("tui-metrics", str(e.exception))
        self.assertIn("maybe", str(e.exception))

    def test_an_unset_value_is_refused_rather_than_defaulted(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(max_agents="5").tui_metrics()
        self.assertIn("tui-metrics", str(e.exception))

    def test_the_env_var_overrides_the_file(self):
        cfg = _cfg(environ={"LC_TUI_METRICS": "true"}, tui_metrics="false")
        self.assertTrue(cfg.tui_metrics())

    def test_it_is_seeded_false_in_the_default_config(self):
        self.assertEqual(dict(_SEED_KEYS)["tui-metrics"], "false")


class TestDeveloperMode(unittest.TestCase):
    def test_reads_true_and_false_from_the_config_file(self):
        self.assertTrue(_cfg(developer_mode="true").developer_mode())
        self.assertFalse(_cfg(developer_mode="false").developer_mode())

    def test_accepts_the_documented_spellings_case_insensitively(self):
        for raw in ("TRUE", "Yes", "1", "on"):
            self.assertTrue(_cfg(developer_mode=raw).developer_mode(), raw)
        for raw in ("FALSE", "No", "0", "off"):
            self.assertFalse(_cfg(developer_mode=raw).developer_mode(), raw)

    def test_a_value_that_is_neither_is_refused_naming_the_key(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(developer_mode="maybe").developer_mode()
        self.assertIn("developer-mode", str(e.exception))

    def test_an_unset_value_is_refused_rather_than_defaulted(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(max_agents="5").developer_mode()
        self.assertIn("developer-mode", str(e.exception))

    def test_the_env_var_overrides_the_file(self):
        cfg = _cfg(environ={"LC_DEVELOPER_MODE": "true"}, developer_mode="false")
        self.assertTrue(cfg.developer_mode())

    def test_it_is_seeded_false_in_the_default_config(self):
        self.assertEqual(dict(_SEED_KEYS)["developer-mode"], "false")

    def test_reconcile_appends_it_to_a_config_without_it(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config")
        Path(p).write_text("projects: /p\n")
        added = Config(environ={"LC_CONFIG": p}).reconcile_config()
        self.assertIn("developer-mode", added)
        self.assertIn("developer-mode: false", Path(p).read_text())


class TestTuiUpgradeCheckSeconds(unittest.TestCase):
    def test_reads_value_from_config_file(self):
        self.assertEqual(
            _cfg(tui_upgrade_check_seconds="1800").tui_upgrade_check_seconds(), 1800
        )

    def test_zero_is_accepted(self):
        self.assertEqual(_cfg(tui_upgrade_check_seconds="0").tui_upgrade_check_seconds(), 0)

    def test_negative_is_refused_naming_the_key_via_config(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(tui_upgrade_check_seconds="-1").tui_upgrade_check_seconds()
        self.assertIn("tui-upgrade-check-seconds", str(e.exception))

    def test_negative_is_refused_naming_the_key_via_env(self):
        with self.assertRaises(ConfigError) as e:
            _cfg({"LC_TUI_UPGRADE_CHECK_SECONDS": "-1"}).tui_upgrade_check_seconds()
        self.assertIn("tui-upgrade-check-seconds", str(e.exception))

    def test_a_malformed_value_is_refused_naming_the_key(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(tui_upgrade_check_seconds="soon").tui_upgrade_check_seconds()
        self.assertIn("tui-upgrade-check-seconds", str(e.exception))

    def test_an_unset_value_is_refused_rather_than_defaulted(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(max_agents="5").tui_upgrade_check_seconds()
        self.assertIn("tui-upgrade-check-seconds", str(e.exception))

    def test_the_env_var_overrides_the_file(self):
        cfg = _cfg(
            environ={"LC_TUI_UPGRADE_CHECK_SECONDS": "60"}, tui_upgrade_check_seconds="1800"
        )
        self.assertEqual(cfg.tui_upgrade_check_seconds(), 60)

    def test_it_is_seeded_fifteen_minutes_in_the_default_config(self):
        self.assertEqual(dict(_SEED_KEYS)["tui-upgrade-check-seconds"], "900")


class TestTuiDoctorCheckSeconds(unittest.TestCase):
    def test_reads_value_from_config_file(self):
        self.assertEqual(
            _cfg(tui_doctor_check_seconds="1800").tui_doctor_check_seconds(), 1800
        )

    def test_zero_is_accepted(self):
        self.assertEqual(_cfg(tui_doctor_check_seconds="0").tui_doctor_check_seconds(), 0)

    def test_negative_is_refused_naming_the_key_via_config(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(tui_doctor_check_seconds="-1").tui_doctor_check_seconds()
        self.assertIn("tui-doctor-check-seconds", str(e.exception))

    def test_negative_is_refused_naming_the_key_via_env(self):
        with self.assertRaises(ConfigError) as e:
            _cfg({"LC_TUI_DOCTOR_CHECK_SECONDS": "-1"}).tui_doctor_check_seconds()
        self.assertIn("tui-doctor-check-seconds", str(e.exception))

    def test_a_malformed_value_is_refused_naming_the_key(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(tui_doctor_check_seconds="soon").tui_doctor_check_seconds()
        self.assertIn("tui-doctor-check-seconds", str(e.exception))

    def test_an_unset_value_is_refused_rather_than_defaulted(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(max_agents="5").tui_doctor_check_seconds()
        self.assertIn("tui-doctor-check-seconds", str(e.exception))

    def test_the_env_var_overrides_the_file(self):
        cfg = _cfg(
            environ={"LC_TUI_DOCTOR_CHECK_SECONDS": "60"}, tui_doctor_check_seconds="1800"
        )
        self.assertEqual(cfg.tui_doctor_check_seconds(), 60)

    def test_it_is_seeded_an_hour_in_the_default_config(self):
        self.assertEqual(dict(_SEED_KEYS)["tui-doctor-check-seconds"], "3600")


class TestPoolUpgradeCheckSeconds(unittest.TestCase):
    def test_reads_value_from_config_file(self):
        self.assertEqual(
            _cfg(pool_upgrade_check_seconds="1800").pool_upgrade_check_seconds(), 1800
        )

    def test_zero_is_accepted(self):
        self.assertEqual(_cfg(pool_upgrade_check_seconds="0").pool_upgrade_check_seconds(), 0)

    def test_negative_is_refused_naming_the_key_via_config(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(pool_upgrade_check_seconds="-1").pool_upgrade_check_seconds()
        self.assertIn("pool-upgrade-check-seconds", str(e.exception))

    def test_negative_is_refused_naming_the_key_via_env(self):
        with self.assertRaises(ConfigError) as e:
            _cfg({"LC_POOL_UPGRADE_CHECK_SECONDS": "-1"}).pool_upgrade_check_seconds()
        self.assertIn("pool-upgrade-check-seconds", str(e.exception))

    def test_a_malformed_value_is_refused_naming_the_key(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(pool_upgrade_check_seconds="soon").pool_upgrade_check_seconds()
        self.assertIn("pool-upgrade-check-seconds", str(e.exception))

    def test_an_unset_value_is_refused_rather_than_defaulted(self):
        with self.assertRaises(ConfigError) as e:
            _cfg(max_agents="5").pool_upgrade_check_seconds()
        self.assertIn("pool-upgrade-check-seconds", str(e.exception))

    def test_the_env_var_overrides_the_file(self):
        cfg = _cfg(
            environ={"LC_POOL_UPGRADE_CHECK_SECONDS": "60"}, pool_upgrade_check_seconds="1800"
        )
        self.assertEqual(cfg.pool_upgrade_check_seconds(), 60)

    def test_it_is_seeded_fifteen_minutes_in_the_default_config(self):
        self.assertEqual(dict(_SEED_KEYS)["pool-upgrade-check-seconds"], "900")


class TestWorkflowsRemoteSeed(unittest.TestCase):
    def test_it_is_seeded_blank_in_the_default_config(self):
        self.assertEqual(dict(_SEED_KEYS)["workflows-remote"], "")


class TestVersion(unittest.TestCase):
    def test_returns_the_package_version(self):
        from lightcycle import __version__

        self.assertEqual(_cfg().version(), __version__)


if __name__ == "__main__":
    unittest.main()


class TestGuidanceRetirementConfig(unittest.TestCase):
    _CASES = (
        ("guidance-unused-after-deliveries", "LC_GUIDANCE_UNUSED_AFTER_DELIVERIES",
         "guidance_unused_after_deliveries"),
        ("guidance-dormant-days", "LC_GUIDANCE_DORMANT_DAYS", "guidance_dormant_days"),
    )

    def test_seeded_default_is_sixty(self):
        seeds = dict(_SEED_KEYS)
        for key, _env, getter in self._CASES:
            self.assertEqual(seeds[key], "60", key)
            self.assertEqual(getattr(_cfg(**{key.replace("-", "_"): seeds[key]}), getter)(), 60)

    def test_env_override_wins(self):
        for key, env, getter in self._CASES:
            c = _cfg({env: "7"}, **{key.replace("-", "_"): "60"})
            self.assertEqual(getattr(c, getter)(), 7, key)

    def test_zero_and_negative_are_refused_naming_the_key(self):
        for key, env, getter in self._CASES:
            for bad in ("0", "-1"):
                with self.assertRaises(ConfigError) as ctx:
                    getattr(_cfg(**{key.replace("-", "_"): bad}), getter)()
                self.assertIn(key, str(ctx.exception))
                with self.assertRaises(ConfigError):
                    getattr(_cfg({env: bad}), getter)()


class TestGithubReserveCalls(unittest.TestCase):
    def test_seeded_at_seven_hundred_and_fifty(self):
        self.assertEqual(dict(_SEED_KEYS)["github-reserve-calls"], "750")

    def test_the_file_value_is_read(self):
        self.assertEqual(_cfg(github_reserve_calls="500").github_reserve_calls(), 500)

    def test_env_override_wins(self):
        c = _cfg({"LC_GITHUB_RESERVE_CALLS": "7"}, github_reserve_calls="750")
        self.assertEqual(c.github_reserve_calls(), 7)

    def test_zero_is_accepted_and_turns_the_hold_off(self):
        self.assertEqual(_cfg(github_reserve_calls="0").github_reserve_calls(), 0)

    def test_negative_is_refused_naming_the_key(self):
        with self.assertRaises(ConfigError) as ctx:
            _cfg(github_reserve_calls="-1").github_reserve_calls()
        self.assertIn("github-reserve-calls", str(ctx.exception))

    def test_missing_fails_naming_the_key(self):
        with self.assertRaises(ConfigError) as ctx:
            _cfg(spin_cap="3").github_reserve_calls()
        self.assertIn("github-reserve-calls", str(ctx.exception))

    def test_shows_in_the_seeded_key_report(self):
        self.assertIn("github-reserve-calls", [k for k, _v in _SEED_KEYS])


class TestPrependPath(unittest.TestCase):
    def test_the_directory_ends_up_first(self):
        env = {"PATH": "/usr/bin:/bin"}

        Config(environ=env).prepend_path("/shims")

        self.assertEqual(env["PATH"], "/shims:/usr/bin:/bin")

    def test_prepending_twice_leaves_path_unchanged(self):
        env = {"PATH": "/usr/bin"}
        c = Config(environ=env)
        c.prepend_path("/shims")

        c.prepend_path("/shims")

        self.assertEqual(env["PATH"], "/shims:/usr/bin")

    def test_a_directory_already_further_along_moves_to_the_front(self):
        env = {"PATH": "/usr/bin:/shims:/bin"}

        Config(environ=env).prepend_path("/shims")

        self.assertEqual(env["PATH"], "/shims:/usr/bin:/bin")

    def test_an_empty_path_becomes_just_the_directory(self):
        env = {}

        Config(environ=env).prepend_path("/shims")

        self.assertEqual(env["PATH"], "/shims")


class TestAgentEnv(unittest.TestCase):
    def _pin(self):
        return Config(environ={}).engine_root()

    def _env(self, pythonpath, **extra):
        env = dict(extra)
        if pythonpath is not None:
            env["PYTHONPATH"] = pythonpath
        return Config(environ=env)

    def test_pin_only_removes_key(self):
        c = self._env(self._pin(), KEEP="1")
        out = c.agent_env()
        self.assertNotIn("PYTHONPATH", out)
        self.assertEqual(out["KEEP"], "1")

    def test_pin_plus_user_entry_keeps_user_entry(self):
        c = self._env(self._pin() + os.pathsep + "/u")
        self.assertEqual(c.agent_env()["PYTHONPATH"], "/u")

    def test_pin_twice_plus_user_entry(self):
        pin = self._pin()
        c = self._env(os.pathsep.join([pin, pin, "/u"]))
        self.assertEqual(c.agent_env()["PYTHONPATH"], "/u")

    def test_user_only_unchanged(self):
        self.assertEqual(self._env("/u").agent_env()["PYTHONPATH"], "/u")

    def test_no_pythonpath_unchanged(self):
        c = self._env(None, KEEP="1")
        self.assertEqual(c.agent_env(), {"KEEP": "1"})

    def test_symlinked_pin_removed(self):
        link = os.path.join(tempfile.mkdtemp(), "engine")
        os.symlink(self._pin(), link)
        c = self._env(link + os.pathsep + "/u")
        self.assertEqual(c.agent_env()["PYTHONPATH"], "/u")

    def test_empty_segments_around_pin_removed(self):
        c = self._env(os.pathsep + self._pin() + os.pathsep)
        self.assertNotIn("PYTHONPATH", c.agent_env())

    def test_result_is_a_copy(self):
        c = self._env("/u")
        c.agent_env()["PYTHONPATH"] = "/x"
        self.assertEqual(c.agent_env()["PYTHONPATH"], "/u")

    def test_matches_the_pin_the_spawner_builds(self):
        import lightcycle.adapters.spawner as spawner
        built = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(spawner.__file__))))
        self.assertEqual(os.path.realpath(built), os.path.realpath(self._pin()))
        c = self._env(built + os.pathsep + "/u")
        self.assertEqual(c.agent_env()["PYTHONPATH"], "/u")


_SCHEDULE_BLOCK = (
    "schedule-weekly-audit:\n"
    "  enabled: false\n"
    "  workflow: lightcycle/material-audit\n"
    "  project: lightcycle\n"
    "  cron: 0 9 * * 1\n"
    "  guard: materials-changed\n"
)


class TestScheduleConfig(unittest.TestCase):
    def _file_cfg(self, text):
        p = os.path.join(tempfile.mkdtemp(), "config")
        Path(p).write_text(text)
        return Config(environ={"LC_CONFIG": p}), p

    def _seeded_without_pause(self):
        return "".join(
            "%s: %s\n" % (k, v) for k, v in _SEED_KEYS if k != "schedules-paused")

    def test_schedules_paused_is_a_seed_key_defaulting_to_false(self):
        self.assertIn(("schedules-paused", "false"), _SEED_KEYS)

    def test_reconcile_appends_the_pause_key_once_and_leaves_a_block_byte_identical(self):
        c, p = self._file_cfg(self._seeded_without_pause() + _SCHEDULE_BLOCK)

        c.ensure_config()
        after_first = Path(p).read_text()
        c.ensure_config()
        c.reconcile_config()
        after_third = Path(p).read_text()

        self.assertIn(_SCHEDULE_BLOCK, after_first)
        self.assertEqual(after_first.count("schedules-paused: false\n"), 1)
        self.assertEqual(after_first, after_third)
        self.assertEqual(c.schedule_blocks()["weekly-audit"]["enabled"], "false")

    def test_a_present_pause_key_is_never_altered(self):
        text = self._seeded_without_pause() + "schedules-paused: true\n" + _SCHEDULE_BLOCK
        c, p = self._file_cfg(text)

        c.ensure_config()
        c.reconcile_config()

        self.assertEqual(Path(p).read_text(), text)
        self.assertTrue(c.schedules_paused())

    def test_an_unreadable_pause_value_is_a_value_error(self):
        c, _p = self._file_cfg("schedules-paused: maybe\n")
        with self.assertRaises(ConfigValueError):
            c.schedules_paused()

    def test_schedule_blocks_are_only_the_schedule_prefixed_dicts(self):
        c, _p = self._file_cfg("schedules-paused: false\nschedule-x:\n  enabled: true\n")
        self.assertEqual(c.schedule_blocks(), {"x": {"enabled": "true"}})

    def test_schedule_keys_are_not_obsolete_but_other_unknown_keys_are(self):
        c, _p = self._file_cfg(
            self._seeded_without_pause() + _SCHEDULE_BLOCK + "scheduler-thing: 1\n")
        self.assertEqual(c.obsolete_config_keys(), ("scheduler-thing",))


def _file_config_with(text):
    path = os.path.join(tempfile.mkdtemp(), "config")
    seeded = "".join("%s: %s\n" % (k, v) for k, v in _SEED_KEYS)
    Path(path).write_text(seeded + text)
    return Config(environ={"LC_CONFIG": path, "LC_HOME": tempfile.mkdtemp()}), path


class TestWorkflowLifecycleConfig(unittest.TestCase):
    def test_the_hook_timeout_is_seeded_and_ranged(self):
        c, _ = _file_config_with("")
        self.assertEqual(c.lifecycle_timeout_seconds(), 300)
        c, _ = _file_config_with("lifecycle-timeout-seconds: 0\n")
        with self.assertRaises(ConfigValueError):
            c.lifecycle_timeout_seconds()

    def test_workflow_config_is_the_named_block_or_empty(self):
        c, _ = _file_config_with("workflow-acme-build:\n  api-token: tok\n  region: eu\n")
        self.assertEqual(c.workflow_config("acme", "build"), {"api-token": "tok", "region": "eu"})
        self.assertEqual(c.workflow_config("acme", "other"), {})

    def test_workflow_config_edits_are_read_on_the_next_load(self):
        c, path = _file_config_with("workflow-acme-build:\n  api-token: one\n")
        self.assertEqual(c.workflow_config("acme", "build")["api-token"], "one")
        Path(path).write_text(Path(path).read_text().replace("one", "two"))
        c.reload()
        self.assertEqual(c.workflow_config("acme", "build")["api-token"], "two")

    def test_the_data_dir_sits_under_the_data_root_beside_workflows(self):
        c, _ = _file_config_with("")
        self.assertEqual(
            c.workflow_data_dir("acme", "build"),
            os.path.join(c.data_root(), "workflow-data", "acme", "build"))

    def test_a_workflow_dict_block_is_not_obsolete_but_a_scalar_one_is(self):
        c, _ = _file_config_with(
            "workflow-acme-build:\n  api-token: tok\nworkflow-stray: 1\nscheduler-thing: 1\n")
        self.assertEqual(c.obsolete_config_keys(), ("workflow-stray", "scheduler-thing"))


class TestCiCheckCeilingConfig(unittest.TestCase):
    def test_seeded_default_is_3600(self):
        seeds = dict(_SEED_KEYS)
        self.assertEqual(seeds["ci-check-ceiling-seconds"], "3600")
        c = _cfg(ci_check_ceiling_seconds=seeds["ci-check-ceiling-seconds"])
        self.assertEqual(c.ci_check_ceiling_seconds(), 3600)

    def test_env_override_wins(self):
        c = _cfg({"LC_CI_CHECK_CEILING_SECONDS": "10"}, ci_check_ceiling_seconds="3600")
        self.assertEqual(c.ci_check_ceiling_seconds(), 10)

    def test_zero_and_negative_are_refused(self):
        for bad in ("0", "-1"):
            with self.assertRaises(ConfigError) as ctx:
                _cfg(ci_check_ceiling_seconds=bad).ci_check_ceiling_seconds()
            self.assertIn("ci-check-ceiling-seconds", str(ctx.exception))
        with self.assertRaises(ConfigError):
            _cfg({"LC_CI_CHECK_CEILING_SECONDS": "0"}).ci_check_ceiling_seconds()

    def test_missing_key_names_it(self):
        with self.assertRaises(ConfigError) as ctx:
            _cfg().ci_check_ceiling_seconds()
        self.assertIn("ci-check-ceiling-seconds", str(ctx.exception))


class TestCiEmptyHeadConfig(unittest.TestCase):
    _KEYS = (
        ("ci-start-window-seconds", "LC_CI_START_WINDOW_SECONDS", "ci_start_window_seconds", "600"),
        ("ci-no-workflows-wait-seconds", "LC_CI_NO_WORKFLOWS_WAIT_SECONDS", "ci_no_workflows_wait_seconds", "60"),
        ("ci-unconfirmed-note-polls", "LC_CI_UNCONFIRMED_NOTE_POLLS", "ci_unconfirmed_note_polls", "3"),
        ("release-hold-note-seconds", "LC_RELEASE_HOLD_NOTE_SECONDS", "release_hold_note_seconds", "60"),
    )

    def test_seeded_defaults(self):
        seeds = dict(_SEED_KEYS)
        for key, _env, getter, default in self._KEYS:
            self.assertEqual(seeds[key], default)
            self.assertEqual(getattr(_cfg(**{getter: default}), getter)(), int(default))

    def test_env_override_wins(self):
        for _key, env, getter, default in self._KEYS:
            self.assertEqual(getattr(_cfg({env: "7"}, **{getter: default}), getter)(), 7)

    def test_zero_and_negative_are_refused_naming_the_key(self):
        for key, _env, getter, _default in self._KEYS:
            for bad in ("0", "-1"):
                with self.assertRaises(ConfigError) as ctx:
                    getattr(_cfg(**{getter: bad}), getter)()
                self.assertIn(key, str(ctx.exception))

    def test_missing_key_names_it(self):
        for key, _env, getter, _default in self._KEYS:
            with self.assertRaises(ConfigError) as ctx:
                getattr(_cfg(), getter)()
            self.assertIn(key, str(ctx.exception))


class TestTickTimingKeys(unittest.TestCase):
    _CASES = (
        ("tick-lag-window-seconds", "LC_TICK_LAG_WINDOW_SECONDS", "tick_lag_window_seconds", "300", 1, None),
        ("tick-lag-share", "LC_TICK_LAG_SHARE", "tick_lag_share", "50", 1, 100),
        ("tick-stall-seconds", "LC_TICK_STALL_SECONDS", "tick_stall_seconds", "120", 1, None),
    )

    def test_seeded_values(self):
        for key, _env, _getter, seed, _lo, _hi in self._CASES:
            self.assertEqual(dict(_SEED_KEYS)[key], seed, key)

    def test_the_file_value_is_read(self):
        for key, _env, getter, _seed, _lo, _hi in self._CASES:
            self.assertEqual(getattr(_cfg(**{key.replace("-", "_"): "42"}), getter)(), 42, key)

    def test_env_override_wins(self):
        for key, env, getter, _seed, _lo, _hi in self._CASES:
            c = _cfg({env: "7"}, **{key.replace("-", "_"): "42"})
            self.assertEqual(getattr(c, getter)(), 7, key)

    def test_bounds_are_accepted_and_beyond_them_refused_naming_the_key(self):
        for key, _env, getter, _seed, lo, hi in self._CASES:
            kw = key.replace("-", "_")
            self.assertEqual(getattr(_cfg(**{kw: str(lo)}), getter)(), lo, key)
            with self.assertRaises(ConfigError) as ctx:
                getattr(_cfg(**{kw: str(lo - 1)}), getter)()
            self.assertIn(key, str(ctx.exception))
            if hi is not None:
                self.assertEqual(getattr(_cfg(**{kw: str(hi)}), getter)(), hi, key)
                with self.assertRaises(ConfigError):
                    getattr(_cfg(**{kw: str(hi + 1)}), getter)()

    def test_missing_fails_naming_the_key(self):
        for key, _env, getter, _seed, _lo, _hi in self._CASES:
            with self.assertRaises(ConfigError) as ctx:
                getattr(_cfg(spin_cap="3"), getter)()
            self.assertIn(key, str(ctx.exception))


class TestTuiHealthIconConfig(unittest.TestCase):
    _KEYS = (
        "tui-health-icon-dir", "tui-health-icon-0", "tui-health-icon-1", "tui-health-icon-2",
        "tui-health-icon-3", "tui-health-icon-4", "tui-health-icon-busy",
    )

    def test_seeds(self):
        seeds = dict(_SEED_KEYS)
        self.assertEqual(seeds["tui-health-icons"], "off")
        self.assertEqual(seeds["tui-health-icon-dir"], "icons")
        for state in ("0", "1", "2", "3", "4"):
            self.assertEqual(seeds["tui-health-icon-%s" % state], "health-%s.png" % state)
        self.assertEqual(seeds["tui-health-icon-busy"], "health-busy.png")

    def test_toggle_parses_on_and_off(self):
        self.assertTrue(_cfg(tui_health_icons="on").tui_health_icons())
        self.assertFalse(_cfg(tui_health_icons="off").tui_health_icons())

    def test_toggle_env_override(self):
        cfg = _cfg(environ={"LC_TUI_HEALTH_ICONS": "on"}, tui_health_icons="off")
        self.assertTrue(cfg.tui_health_icons())

    def test_unset_names_the_key(self):
        for key in ("tui-health-icons",) + self._KEYS:
            getter = key.replace("-", "_")
            with self.assertRaises(ConfigError) as e:
                getattr(_cfg(max_agents="5"), getter)()
            self.assertIn(key, str(e.exception))

    def test_getters_return_the_configured_values(self):
        cfg = _cfg(tui_health_icon_dir="faces", tui_health_icon_0="a.png", tui_health_icon_busy="b.png")
        self.assertEqual(cfg.tui_health_icon_dir(), "faces")
        self.assertEqual(cfg.tui_health_icon_0(), "a.png")
        self.assertEqual(cfg.tui_health_icon_busy(), "b.png")
        self.assertEqual(
            cfg.tui_health_icon_path("0"), os.path.join(cfg.data_root(), "faces", "a.png"))

    def test_absolute_and_parent_paths_are_rejected(self):
        for bad in ("/etc/x", "../x", "a/../../x"):
            for key in ("tui_health_icon_dir", "tui_health_icon_3"):
                with self.assertRaises(ConfigError) as e:
                    getattr(_cfg(**{key: bad}), key)()
                self.assertIn("data root", str(e.exception))
