import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lightcycle import cli
from lightcycle.application.setup.config_edit import ConfigEditError, ConfigEditUseCase
from lightcycle.commands.setup import CONFIG_EDIT_RESTART_NOTICE
from lightcycle.config import _SEED_KEYS, Config
from lightcycle.config_schema import KEY_KINDS, NO_USABLE_DEFAULT
from lightcycle.config_seeds import default_config_text
from tests.unit.test_cmd_config import FakeContainer, call


def _home(environ=None):
    d = tempfile.mkdtemp()
    env = {"LC_HOME": d, "LC_CONFIG": os.path.join(d, "config")}
    env.update(environ or {})
    c = Config(environ=env)
    c.ensure_config()
    return c


def _bytes(c):
    return Path(c.config_path()).read_bytes()


class ConfigEditCase(unittest.TestCase):
    def setUp(self):
        self.config = _home()
        self.uc = ConfigEditUseCase(self.config)
        self._orig = cli.container()
        self.addCleanup(lambda: cli.set_container(self._orig))

    def cli(self, *args):
        cli.set_container(FakeContainer(self.config))
        return call(cli.cmd_config, *args)

    def get(self, key):
        return self.uc.get(key).lines


BLANK_LIST_SEEDS = ("review-bots",)


class TestKindTable(unittest.TestCase):
    def test_kinds_and_seed_keys_name_the_same_keys(self):
        self.assertEqual(set(KEY_KINDS), {k for k, _ in _SEED_KEYS})
        self.assertEqual(len(KEY_KINDS), 80)

    def test_kind_sizes(self):
        sizes = {}
        for kind in KEY_KINDS.values():
            sizes[kind] = sizes.get(kind, 0) + 1
        self.assertEqual(sizes, {
            "bool": 5, "int": 38, "float": 14, "path": 4, "relative-path": 7, "list": 3,
            "str": 9})


class TestSeededKeys(ConfigEditCase):
    def test_every_seeded_key_round_trips(self):
        passed = 0
        for key, seed in _SEED_KEYS:
            if key in NO_USABLE_DEFAULT or key in BLANK_LIST_SEEDS:
                continue
            values = seed.split() if KEY_KINDS[key] == "list" else [seed]
            result = self.uc.set(key, values)
            self.assertIsNotNone(result, key)
            setting = next(s for s in self.config.resolved_settings() if s.key == key)
            self.assertEqual(setting.state, "set", key)
            passed += 1
        self.assertEqual(passed, 77)

    def test_blank_seeded_required_keys_refuse(self):
        for key in NO_USABLE_DEFAULT:
            before = _bytes(self.config)
            with self.assertRaises(ConfigEditError):
                self.uc.set(key, [""])
            self.assertEqual(_bytes(self.config), before)

    def test_unknown_key_is_refused(self):
        for call_ in (
            lambda: self.uc.get("nope"), lambda: self.uc.set("nope", ["1"]),
            lambda: self.uc.unset("nope"), lambda: self.uc.add("nope", "x"),
        ):
            with self.assertRaises(ConfigEditError) as ctx:
                call_()
            self.assertIn("unknown config key 'nope'", str(ctx.exception))

    def test_unknown_key_names_the_nearest_match(self):
        with self.assertRaises(ConfigEditError) as ctx:
            self.uc.get("max-age")
        self.assertIn("max-agents", str(ctx.exception))

    def test_refused_set_leaves_file_unchanged(self):
        before = _bytes(self.config)
        for key, value in (
            ("max-agents", "abc"), ("max-agents", "-1"), ("tick-lag-share", "101"),
            ("memory-reserve-fraction", "1.5"), ("schedules-paused", "maybe"),
            ("tui-health-icon-dir", "../x"), ("max-agents", ""), ("trusted-authors", ""),
            ("memory-reserve-fraction", "nan"), ("editor", "a\nb"),
        ):
            with self.assertRaises(ConfigEditError, msg=(key, value)):
                self.uc.set(key, [value])
            self.assertEqual(_bytes(self.config), before, (key, value))

    def test_a_list_key_takes_several_values(self):
        self.uc.set("trusted-authors", ["a b", "c"])
        self.assertEqual(self.get("trusted-authors"), ("a", "b", "c"))

    def test_a_scalar_key_takes_one_value(self):
        with self.assertRaises(ConfigEditError):
            self.uc.set("max-agents", ["1", "2"])

    def test_bool_is_stored_canonically(self):
        self.uc.set("schedules-paused", ["yes"])
        self.assertIn("schedules-paused: true\n", Path(self.config.config_path()).read_text())
        self.assertEqual(self.get("schedules-paused"), ("true",))

    def test_personal_origin_may_be_blank(self):
        self.uc.set("personal-origin", ["mine"])
        self.uc.set("personal-origin", [""])
        self.assertIn("personal-origin: \n", Path(self.config.config_path()).read_text())

    def test_get_prints_the_resolved_value(self):
        self.assertEqual(self.get("max-agents"), ("5",))
        self.assertEqual(self.get("projects"), (self.config.projects_root(),))

    def test_get_of_a_blank_key_says_not_set(self):
        with self.assertRaises(ConfigEditError):
            self.uc.get("personal-origin")

    def test_get_notes_env_override(self):
        c = _home({"LC_MAX_AGENTS": "9"})
        result = ConfigEditUseCase(c).get("max-agents")
        self.assertEqual(result.lines, ("9",))
        self.assertIn("LC_MAX_AGENTS", result.note)
        cli.set_container(FakeContainer(c))
        rc, out, err = call(cli.cmd_config, "get", "max-agents")
        self.assertEqual((rc, out), (0, "9\n"))
        self.assertIn("note: overridden by $LC_MAX_AGENTS", err)

    def test_the_getter_net_ignores_env_overrides(self):
        c = _home({"LC_MAX_AGENTS": "9"})
        self.assertIsNone(c.candidate_problem(c.read_config_text(), "max-agents"))
        broken = c.read_config_text().replace("max-agents: 5", "max-agents: x")
        self.assertIsNotNone(c.candidate_problem(broken, "max-agents"))


class TestLists(ConfigEditCase):
    def test_list_add_remove(self):
        self.uc.add("trusted-authors", "ken")
        self.assertEqual(self.get("trusted-authors"), ("ken",))
        self.uc.add("trusted-authors", "bob")
        self.assertEqual(self.get("trusted-authors"), ("bob", "ken"))
        self.uc.remove("trusted-authors", "bob")
        self.assertEqual(self.get("trusted-authors"), ("ken",))

    def test_review_bots_add_and_unset(self):
        self.uc.add("review-bots", "Copilot")
        self.assertEqual(self.get("review-bots"), ("copilot",))
        self.uc.add("review-bots", "other[bot]")
        self.assertEqual(self.get("review-bots"), ("copilot", "other[bot]"))
        self.uc.unset("review-bots")
        self.assertEqual(self.get("review-bots"), ())

    def test_add_on_a_non_list_refuses(self):
        for verb in (self.uc.add, self.uc.remove):
            with self.assertRaises(ConfigEditError) as ctx:
                verb("max-agents", "1")
            self.assertIn("max-agents is not a list", str(ctx.exception))

    def test_remove_some_of_several_tokens(self):
        self.uc.set("trusted-authors", ["a", "b", "c"])
        self.uc.remove("trusted-authors", "b")
        self.assertEqual(self.get("trusted-authors"), ("a", "c"))

    def test_removing_the_last_token_refuses(self):
        self.uc.add("trusted-authors", "ken")
        before = _bytes(self.config)
        with self.assertRaises(ConfigEditError) as ctx:
            self.uc.remove("trusted-authors", "ken")
        self.assertIn("would leave trusted-authors empty", str(ctx.exception))
        self.assertEqual(_bytes(self.config), before)

    def test_context_artifact_types_compare_exactly(self):
        self.uc.add("context-artifact-types", "Spec")
        self.assertEqual(self.get("context-artifact-types"), ("Spec", "spec"))

    def test_nothing_to_do_writes_are_noops_that_exit_zero(self):
        self.cli("add", "trusted-authors", "ken")
        self.cli("set", "max-agents", "9")
        self.cli("unset", "max-agents")
        for args in (
            ("add", "trusted-authors", "Ken"),
            ("remove", "trusted-authors", "ghost"),
            ("unset", "max-agents"),
        ):
            for _ in range(2):
                before = _bytes(self.config)
                rc, out, err = self.cli(*args)
                self.assertEqual(rc, 0, (args, err))
                self.assertEqual(_bytes(self.config), before, args)
                self.assertEqual(len(out.strip().splitlines()), 1, (args, out))
                self.assertNotIn(CONFIG_EDIT_RESTART_NOTICE, out)
        rc, out, _ = self.cli("add", "trusted-authors", "Ken")
        self.assertIn("already has", out)
        rc, out, _ = self.cli("remove", "trusted-authors", "ghost")
        self.assertIn("does not have", out)
        rc, out, _ = self.cli("unset", "max-agents")
        self.assertIn("already at its seed", out)


class TestUnset(ConfigEditCase):
    def test_unset_refuses_for_keys_without_a_usable_default(self):
        for key in NO_USABLE_DEFAULT:
            with self.assertRaises(ConfigEditError) as ctx:
                self.uc.unset(key)
            self.assertIn("no usable default", str(ctx.exception))

    def test_unset_resets_to_seed(self):
        self.uc.set("max-agents", ["9"])
        result = self.uc.unset("max-agents")
        self.assertEqual(result.message, "reset max-agents to 5")
        self.assertTrue(result.changed)
        self.assertEqual(self.get("max-agents"), ("5",))

    def test_unset_resets_a_per_home_seed(self):
        self.uc.set("guidance-path", ["/elsewhere"])
        self.uc.unset("guidance-path")
        self.assertEqual(
            self.get("guidance-path"), (os.path.join(self.config.data_root(), "agent-guidance"),))

    def test_every_other_seeded_key_unsets(self):
        for key, seed in _SEED_KEYS:
            if key in NO_USABLE_DEFAULT:
                continue
            self.uc.unset(key)


class TestBlocks(ConfigEditCase):
    def test_callout_block_built_by_dotted_keys(self):
        steps = (
            ("command", "/bin/true", True), ("subject", "pr", True),
            ("principal-outputs", "code", True), ("wait", "true", True),
            ("timeout", "30", False),
        )
        warned = []
        for key, value, _ in steps:
            result = self.uc.set("callout-x.%s" % key, [value])
            warned.append(result.warnings)
        self.assertTrue(warned[0])
        self.assertIn("timeout", " ".join(warned[3]))
        self.assertEqual(warned[4], ())
        self.assertEqual(self.get("callout-x.timeout"), ("30",))
        self.assertEqual(len(self.get("callout-x")), 5)
        self.assertEqual([c.id for c in self.config.callouts()], ["x"])

    def test_callout_rejections(self):
        self.uc.set("callout-x.command", ["/bin/true"])
        before = _bytes(self.config)
        for key, value in (
            ("callout-x.bogus", "1"), ("callout-x.wait", "maybe"), ("callout-x.timeout", "0"),
            ("callout-x.subject", "nope"),
        ):
            with self.assertRaises(ConfigEditError, msg=key):
                self.uc.set(key, [value])
        self.assertEqual(_bytes(self.config), before)

    def test_schedule_key_validation(self):
        for value in ("nope",):
            with self.assertRaises(ConfigEditError):
                self.uc.set("schedule-retro-audit.cron", [value])
        self.uc.set("schedule-retro-audit.cron", ["0 9 * * 1"])
        self.assertEqual(self.get("schedule-retro-audit.cron"), ("0 9 * * 1",))
        with self.assertRaises(ConfigEditError):
            self.uc.set("schedule-retro-audit.enabled", ["maybe"])
        with self.assertRaises(ConfigEditError):
            self.uc.set("schedule-retro-audit.name", ["Bad Name"])
        self.uc.set("schedule-retro-audit.min", ["10"])

    def test_workflow_block_dotted_key(self):
        self.uc.set("workflow-lightcycle-foo.some-key", ["v"])
        text = Path(self.config.config_path()).read_text()
        self.assertIn("workflow-lightcycle-foo:\n  some-key: v\n", text)
        self.assertEqual(self.config.workflow_config("lightcycle", "foo"), {"some-key": "v"})

    def test_a_block_name_with_a_dot_splits_on_the_last_dot(self):
        self.uc.set("workflow-my.origin-foo.some-key", ["v"])
        self.assertEqual(self.config.workflow_config("my.origin", "foo"), {"some-key": "v"})
        self.assertEqual(self.get("workflow-my.origin-foo.some-key"), ("v",))

    def test_unset_last_block_key_removes_header(self):
        self.uc.set("workflow-lightcycle-foo.a", ["1"])
        self.uc.set("workflow-lightcycle-foo.b", ["2"])
        self.uc.unset("workflow-lightcycle-foo.a")
        self.assertEqual(self.get("workflow-lightcycle-foo"), ("b: 2",))
        self.uc.unset("workflow-lightcycle-foo.b")
        self.assertNotIn("workflow-lightcycle-foo", Path(self.config.config_path()).read_text())

    def test_unset_block_removes_all_keys(self):
        self.uc.set("workflow-lightcycle-foo.a", ["1"])
        self.uc.set("workflow-lightcycle-foo.b", ["2"])
        self.uc.unset("workflow-lightcycle-foo")
        self.assertNotIn("workflow-lightcycle-foo", Path(self.config.config_path()).read_text())

    def test_unset_of_a_missing_block_key_is_a_noop(self):
        before = _bytes(self.config)
        result = self.uc.unset("callout-x.command")
        self.assertFalse(result.changed)
        self.assertEqual(_bytes(self.config), before)

    def test_set_on_a_scalar_line_refuses(self):
        with open(self.config.config_path(), "a") as f:
            f.write("callout-x: 1\n")
        self.config.reload()
        before = _bytes(self.config)
        with self.assertRaises(ConfigEditError):
            self.uc.set("callout-x.command", ["/bin/true"])
        self.assertEqual(_bytes(self.config), before)

    def test_setting_a_whole_block_refuses(self):
        with self.assertRaises(ConfigEditError):
            self.uc.set("callout-x", ["1"])

    def test_a_callout_write_runs_the_preflight_for_a_changed_command(self):
        cli.set_container(FakeContainer(self.config, callout_preflight=mock.Mock(
            check=mock.Mock(return_value=[]))))
        for key, value in (
            ("command", "/bin/true"), ("subject", "pr"), ("principal-outputs", "code"),
            ("wait", "false"), ("timeout", "30"),
        ):
            rc, out, err = call(cli.cmd_config, "set", "callout-x.%s" % key, value)
            self.assertEqual(rc, 0, err)
        self.assertTrue(cli.container().callout_preflight.check.called)


class TestFileEdit(ConfigEditCase):
    def test_edit_preserves_other_lines(self):
        text = Path(self.config.config_path()).read_text()
        text = "# looks like: a comment\n\n" + text + "max-agents: 3\n\nstray line\n"
        Path(self.config.config_path()).write_text(text)
        self.config.reload()
        self.uc.set("max-agents", ["7"])
        after = Path(self.config.config_path()).read_text().splitlines(keepends=True)
        self.assertEqual(sum(1 for line in after if line.startswith("max-agents:")), 1)
        before = [l for l in text.splitlines(keepends=True) if not l.startswith("max-agents:")]
        self.assertEqual([l for l in after if not l.startswith("max-agents:")], before)
        self.assertEqual(self.get("max-agents"), ("7",))

    def test_a_missing_trailing_newline_is_repaired_on_append(self):
        seeded = default_config_text(self.config._seed_overrides()).rstrip("\n")
        Path(self.config.config_path()).write_text(seeded)
        self.config.reload()
        self.uc.set("workflow-lightcycle-foo.a", ["1"])
        self.assertEqual(
            Path(self.config.config_path()).read_text(),
            seeded + "\nworkflow-lightcycle-foo:\n  a: 1\n")

    def test_seeded_schedule_blocks_round_trip_byte_identical(self):
        Path(self.config.config_path()).write_text(default_config_text(self.config._seed_overrides()))
        self.config.reload()
        start = _bytes(self.config)
        for sid in ("retro-audit", "material-audit", "daily-summary", "ratchet-sweep"):
            self.uc.set("schedule-%s.enabled" % sid, ["false"])
            self.assertNotEqual(_bytes(self.config), start)
            self.uc.set("schedule-%s.enabled" % sid, ["true"])
        self.assertEqual(_bytes(self.config), start)

    def test_write_is_atomic(self):
        directory = os.path.dirname(self.config.config_path())
        self.uc.set("max-agents", ["7"])
        self.assertEqual(
            [n for n in os.listdir(directory) if n.startswith(".config-")], [])
        before = _bytes(self.config)
        with mock.patch("lightcycle.config.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.uc.set("max-agents", ["8"])
        self.assertEqual(_bytes(self.config), before)
        self.assertEqual(
            [n for n in os.listdir(directory) if n.startswith(".config-")], [])

    def test_pool_reload_accepts_a_command_edit(self):
        pool = Config(environ=dict(self.config._environ))
        pool.load_config()
        self.uc.set("poll-seconds", ["10"])
        st = os.stat(self.config.config_path()).st_mtime_ns + 1_000_000_000
        os.utime(self.config.config_path(), ns=(st, st))
        result = pool.try_reload()
        self.assertEqual(result.outcome, "reloaded")


class TestCli(ConfigEditCase):
    def test_restart_notice_after_write(self):
        rc, out, err = self.cli("set", "poll-seconds", "10")
        self.assertEqual(rc, 0, err)
        self.assertIn("set poll-seconds to 10", out)
        self.assertIn(CONFIG_EDIT_RESTART_NOTICE, out)

    def test_a_refusal_exits_one_and_writes_to_stderr(self):
        before = _bytes(self.config)
        rc, out, err = self.cli("set", "max-agents", "abc")
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("max-agents", err)
        self.assertEqual(_bytes(self.config), before)

    def test_get_of_a_list_prints_one_entry_per_line(self):
        self.cli("set", "trusted-authors", "a", "b")
        rc, out, _ = self.cli("get", "trusted-authors")
        self.assertEqual((rc, out), (0, "a\nb\n"))

    def test_bare_config_still_lists_every_key(self):
        rc, out, _ = self.cli()
        self.assertEqual(rc, 0)
        self.assertIn("max-agents: 5 (seed 5)", out)
