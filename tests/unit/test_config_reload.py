import contextlib
import io
import os
import tempfile
import unittest

from lightcycle.application.pool.reload_config import ReloadConfigUseCase
from lightcycle.application.pool.schedule_cadence import ScheduleCadenceResponse
from lightcycle.application.pool.tick import TickInput
from lightcycle.config import _SEED_KEYS, RESTART_REQUIRED_KEYS, Config
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeConfigReloadStatus
from tests.unit.test_pool import FakeSpawner, FakeWorkers, make_tick


class RecordingScheduleGate:
    def __init__(self, config):
        self._config = config
        self.seen = []
        self.resets = 0

    def execute(self, now):
        self.seen.append((self._config.schedules_paused(), sorted(self._config.schedule_blocks())))
        return ScheduleCadenceResponse()

    def reset(self):
        self.resets += 1


class ReloadFixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.path = os.path.join(self.root, "config")
        self.config = Config(environ={"LC_HOME": self.root, "LC_CONFIG": self.path})
        self.config.ensure_config()
        self.config.load_config()
        self._stamp = os.stat(self.path).st_mtime_ns

    def edit(self, transform):
        with open(self.path) as f:
            text = f.read()
        with open(self.path, "w") as f:
            f.write(transform(text))
        self._stamp += 10_000_000_000
        os.utime(self.path, ns=(self._stamp, self._stamp))

    def set_key(self, key, value):
        def transform(text):
            lines = [ln for ln in text.splitlines() if ln.split(":", 1)[0] != key]
            return "\n".join(lines + ["%s: %s" % (key, value)]) + "\n"
        self.edit(transform)

    def drop_key(self, key):
        self.edit(lambda t: "\n".join(
            ln for ln in t.splitlines() if ln.split(":", 1)[0] != key) + "\n")

    def tick(self, store=None, workers=None, **overrides):
        self.status = FakeConfigReloadStatus()
        self.reload = ReloadConfigUseCase(self.config, self.status, 4242)
        self.gate = RecordingScheduleGate(self.config)
        self.spawner = FakeSpawner()
        kwargs = dict(schedule_gate=self.gate, config_reload=self.reload)
        kwargs.update(overrides)
        return make_tick(
            store or FakeStore(), workers or FakeWorkers(), self.spawner, self.config, **kwargs)

    def run_tick(self, tick):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = tick.execute(TickInput(now=1000.0))
        return result, err.getvalue()


class TestEditBetweenTicks(ReloadFixture):
    def test_schedule_block_and_pause_switch_take_effect_on_the_next_tick(self):
        tick = self.tick()
        first, _ = self.run_tick(tick)
        self.edit(lambda t: t.replace("schedules-paused: false", "schedules-paused: true")
                  + "schedule-x:\n  enabled: true\n  cron: \"0 9 * * *\"\n")
        second, _ = self.run_tick(tick)
        seeded = ["daily-summary", "material-audit", "ratchet-sweep", "retro-audit"]
        self.assertEqual(self.gate.seen[0], (False, seeded))
        self.assertEqual(self.gate.seen[1], (True, seeded + ["x"]))
        self.assertEqual(first.config.outcome, "unchanged")
        self.assertEqual(second.config.outcome, "reloaded")

    def test_reloaded_result_resets_the_schedule_gate(self):
        tick = self.tick()
        self.run_tick(tick)
        self.assertEqual(self.gate.resets, 0)
        self.set_key("schedules-paused", "true")
        self.run_tick(tick)
        self.assertEqual(self.gate.resets, 1)
        self.run_tick(tick)
        self.assertEqual(self.gate.resets, 1)


class TestRejectedEdits(ReloadFixture):
    def assert_kept_and_warned_once(self, tick):
        result, err = self.run_tick(tick)
        self.assertEqual(result.config.outcome, "rejected")
        self.assertEqual(err.count("config reload rejected"), 1)
        for _ in range(2):
            again, more = self.run_tick(tick)
            self.assertEqual(again.config.outcome, "unchanged")
            self.assertEqual(more, "")
        self.assertEqual(self.gate.resets, 0)

    def test_a_deleted_required_key_keeps_the_previous_config(self):
        tick = self.tick()
        self.drop_key("max-agents")
        self.assert_kept_and_warned_once(tick)
        self.assertEqual(self.config.max_agents(), 5)

    def test_a_value_a_getter_rejects_keeps_the_previous_config(self):
        tick = self.tick()
        self.set_key("max-agents", "abc")
        self.assert_kept_and_warned_once(tick)
        self.assertEqual(self.config.max_agents(), 5)

    def test_a_valid_edit_after_a_rejection_reloads(self):
        tick = self.tick()
        self.set_key("max-agents", "abc")
        self.run_tick(tick)
        self.set_key("max-agents", "7")
        result, _ = self.run_tick(tick)
        self.assertEqual(result.config.outcome, "reloaded")
        self.assertEqual(self.config.max_agents(), 7)

    def test_a_missing_file_is_rejected_and_the_previous_config_kept(self):
        tick = self.tick()
        os.remove(self.path)
        result, err = self.run_tick(tick)
        self.assertEqual(result.config.outcome, "rejected")
        self.assertIn("missing", err)
        self.assertEqual(self.config.max_agents(), 5)

    def test_unreadable_bytes_are_rejected_and_the_previous_config_kept(self):
        tick = self.tick()
        with open(self.path, "wb") as f:
            f.write(b"max-agents: \xff\xfe\n")
        self._stamp += 10_000_000_000
        os.utime(self.path, ns=(self._stamp, self._stamp))
        result, err = self.run_tick(tick)
        self.assertEqual(result.config.outcome, "rejected")
        self.assertIn("could not be read", err)
        self.assertEqual(self.config.max_agents(), 5)

    def test_the_rejection_is_recorded_on_the_status_port(self):
        tick = self.tick()
        self.set_key("max-agents", "abc")
        self.run_tick(tick)
        state = self.status.load()
        self.assertEqual(state.outcome, "rejected")
        self.assertEqual(state.pid, 4242)
        self.assertEqual(state.rejected_mtime, self.config.config_mtime())


class TestRestartRequiredKeys(ReloadFixture):
    def test_mixed_edit_applies_live_keys_and_names_the_restart_key(self):
        tick = self.tick()
        self.run_tick(tick)
        self.set_key("poll-seconds", "9")
        self.set_key("schedules-paused", "true")
        result, _ = self.run_tick(tick)
        self.assertEqual(result.config.outcome, "reloaded")
        self.assertEqual(result.config.restart_required, ("poll-seconds",))
        self.assertTrue(self.config.schedules_paused())
        self.assertEqual(self.status.load().restart_required, ("poll-seconds",))

    def test_an_edit_leaving_the_four_keys_alone_needs_no_restart(self):
        tick = self.tick()
        self.set_key("max-agents", "6")
        result, _ = self.run_tick(tick)
        self.assertEqual(result.config.restart_required, ())

    def test_an_mtime_only_touch_reloads_with_no_restart_keys(self):
        tick = self.tick()
        self.edit(lambda t: t)
        result, _ = self.run_tick(tick)
        self.assertEqual(result.config.outcome, "reloaded")
        self.assertEqual(result.config.restart_required, ())

    def test_every_restart_required_key_is_a_seed_key(self):
        self.assertTrue(set(RESTART_REQUIRED_KEYS) <= {k for k, _ in _SEED_KEYS})

    def test_reverting_the_edit_clears_the_restart_requirement(self):
        tick = self.tick()
        self.set_key("tick-failure-cap", "9")
        self.run_tick(tick)
        self.set_key("tick-failure-cap", "5")
        result, _ = self.run_tick(tick)
        self.assertEqual(result.config.restart_required, ())


class TestScheduleCadenceReset(unittest.TestCase):
    def test_reset_clears_both_caches(self):
        from lightcycle.application.pool.schedule_cadence import ScheduleCadenceUseCase

        uc = ScheduleCadenceUseCase(None, None, None, None, None, None, None, None)
        uc._evaluated["x"] = 1
        uc._warned["x"] = "reason"
        uc.reset()
        self.assertEqual((uc._evaluated, uc._warned), ({}, {}))


class TestBoundary(ReloadFixture):
    def test_first_tick_with_an_untouched_file_is_unchanged(self):
        result, err = self.run_tick(self.tick())
        self.assertEqual(result.config.outcome, "unchanged")
        self.assertEqual(err, "")
        self.assertEqual(self.status.load().outcome, "unchanged")

    def test_seeded_real_content_touched_is_reloaded_not_rejected(self):
        tick = self.tick()
        self.edit(lambda t: t)
        result, _ = self.run_tick(tick)
        self.assertEqual(result.config.outcome, "reloaded")


class TestMaxAgentsIsLive(ReloadFixture):
    def ready_steps(self, store, n):
        for _ in range(n):
            item = store.create_item("i", "d")
            store.create_step(stage="build", role="agent", item=item)

    def test_raising_max_agents_spawns_up_to_the_new_value(self):
        store = FakeStore()
        self.ready_steps(store, 4)
        tick = self.tick(store=store)
        self.set_key("max-agents", "1")
        self.run_tick(tick)
        self.assertEqual(len(self.spawner.spawned), 1)
        self.set_key("max-agents", "3")
        self.run_tick(tick)
        self.assertEqual(len(self.spawner.spawned), 4)

    def test_lowering_max_agents_below_the_live_count_spawns_and_kills_nothing(self):
        store = FakeStore()
        self.ready_steps(store, 3)
        first = store.claim_ready("agent", "a")
        second = store.claim_ready("agent", "b")
        workers = FakeWorkers(workers=[
            {"role": "agent", "pid": 1, "step": first.id, "spawnid": "a"},
            {"role": "agent", "pid": 2, "step": second.id, "spawnid": "b"},
        ], alive_pids={1, 2})
        tick = self.tick(store=store, workers=workers)
        self.set_key("max-agents", "1")
        result, _ = self.run_tick(tick)
        self.assertEqual(self.spawner.spawned, [])
        self.assertLessEqual(result.pool.free_slots, 0)
        self.assertEqual(workers.killed, [])


if __name__ == "__main__":
    unittest.main()
