import unittest

from lightcycle.application.flow.park_step import ParkStepUseCase
from lightcycle.application.pool.script_stages import ScriptStageUseCase
from lightcycle.domain.work import State
from lightcycle.ports.github import CheckRun, ReadFailure
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github_poll_runner import BlockingGithubPollRunner
from tests.support.fake_script_runner import FakeScriptRunner
from tests.support.latent_github import LatentGitHub
from tests.support.pool_crash import PoolCrash, crash_on
from tests.support.pool_rig import PoolRig
from tests.support.sim_clock import SimClock
from tests.unit.test_resolve_merged_prs import plant_pr
from tests.unit.test_script_stage_usecase import Rig as ScriptRig
from tests.unit.test_script_stage_usecase import done

_URL = "https://github.com/x/y/pull/7"
_BRANCH = "feat/app-code-login"

_MERGE_FLOW = flow_from_metas({
    "reviewer": {
        "step": "ready-merge",
        "phase": "code",
        "routes": {"merged": "cleanup"},
        "on_pr_merge": "merged",
    },
    "cleaner": {"model": "sonnet", "step": "cleanup", "phase": "code"},
})

_SUCCESS = CheckRun(name="build", status="completed", conclusion="success")


class TestSimClock(unittest.TestCase):
    def test_sleep_advances_the_clock_and_does_not_wait(self):
        clock = SimClock(start=100.0)

        clock.sleep(30)

        self.assertEqual(clock(), 130.0)

    def test_iso_renders_the_simulated_instant(self):
        clock = SimClock(start=0.0)

        clock.advance(86400)

        self.assertEqual(clock.iso(), "1970-01-02T00:00:00+00:00")


class TestLatentGitHub(unittest.TestCase):
    def setUp(self):
        self.clock = SimClock()
        self.github = LatentGitHub(self.clock, head_shas={_URL: "sha1"})

    def test_check_runs_stay_empty_until_the_delay_has_passed_inclusive(self):
        self.github.check_runs_appear(_URL, "sha1", [_SUCCESS], after_seconds=30)

        self.clock.advance(29)
        early = self.github.check_runs(_URL, "sha1")
        self.clock.advance(1)
        on_time = self.github.check_runs(_URL, "sha1")

        self.assertEqual(early, ())
        self.assertEqual(on_time, (_SUCCESS,))

    def test_check_runs_appear_on_the_read_after_the_configured_reads(self):
        self.github.check_runs_appear(_URL, "sha1", [_SUCCESS], after_reads=2)

        reads = [self.github.check_runs(_URL, "sha1") for _ in range(3)]

        self.assertEqual(reads, [(), (), (_SUCCESS,)])

    def test_a_workflow_run_appears_after_its_delay(self):
        self.github.workflow_run_appears(_URL, "sha1", count=2, after_seconds=10)

        before = self.github.workflow_runs(_URL, "sha1")
        self.clock.advance(10)
        after = self.github.workflow_runs(_URL, "sha1")

        self.assertEqual((before, after), (0, 2))

    def test_fail_call_fails_only_the_listed_call(self):
        self.github.fail_call("head_sha", on=(2,))

        reads = [self.github.head_sha(_URL) for _ in range(3)]

        self.assertEqual(reads[0], "sha1")
        self.assertEqual(reads[1], ReadFailure(1, "boom"))
        self.assertEqual(reads[2], "sha1")

    def test_fail_call_restricted_to_a_pr_ignores_other_prs(self):
        other = "https://github.com/x/y/pull/8"
        self.github.fail_call("head_sha", pr=other)

        self.assertEqual(self.github.head_sha(_URL), "sha1")
        self.assertIsInstance(self.github.head_sha(other), ReadFailure)

    def test_time_out_call_returns_the_adapters_timeout_shape(self):
        self.github.time_out_call("head_sha")

        self.assertEqual(self.github.head_sha(_URL), ReadFailure(-1, "gh timed out after 60s"))

    def test_read_takes_advances_the_clock_on_every_read(self):
        self.github.read_takes("head_sha", 7)

        self.github.head_sha(_URL)
        self.github.head_sha(_URL)

        self.assertEqual(self.clock(), 10014.0)
        self.assertEqual(self.github.counts["head_sha"], 2)

    def test_push_moves_the_head_and_the_updated_at(self):
        self.clock.advance(50)

        self.github.push(_URL, "sha2")

        self.assertEqual(self.github.head_sha(_URL), "sha2")
        self.assertEqual(self.github.pr_view(_URL).updated_at, self.clock())

    def test_merge_marks_the_pr_merged_and_bumps_updated_at(self):
        self.clock.advance(5)

        self.github.merge(_URL)

        self.assertTrue(self.github.is_merged(_URL))
        self.assertEqual(self.github.pr_view(_URL).updated_at, self.clock())


class _Target:
    def __init__(self):
        self.seen = []

    def work(self, value):
        self.seen.append(value)
        return value


class TestCrashPoint(unittest.TestCase):
    def test_a_pool_crash_is_not_an_exception(self):
        self.assertFalse(issubclass(PoolCrash, Exception))

    def test_after_applies_the_effect_then_raises_once_at_the_nth_call(self):
        target = _Target()
        point = crash_on(target, "work", nth=2)

        target.work(1)
        with self.assertRaises(PoolCrash):
            target.work(2)
        target.work(3)

        self.assertEqual(target.seen, [1, 2, 3])
        self.assertTrue(point.fired)

    def test_before_raises_without_the_effect(self):
        target = _Target()
        crash_on(target, "work", when="before")

        with self.assertRaises(PoolCrash):
            target.work(1)

        self.assertEqual(target.seen, [])

    def test_match_counts_only_the_calls_it_accepts(self):
        target = _Target()
        point = crash_on(target, "work", nth=2, match=lambda value: value > 10)

        target.work(1)
        target.work(11)
        target.work(2)
        with self.assertRaises(PoolCrash):
            target.work(12)

        self.assertEqual(point.calls, 2)

    def test_disarm_removes_the_instance_attribute(self):
        target = _Target()
        point = crash_on(target, "work")

        point.disarm()

        self.assertNotIn("work", vars(target))
        target.work(1)
        self.assertFalse(point.fired)

    def test_an_unknown_moment_is_refused(self):
        with self.assertRaises(ValueError):
            crash_on(_Target(), "work", when="during")


class _MergedPrRig:
    def __init__(self):
        self.clock = SimClock()
        self.github = LatentGitHub(
            self.clock, head_shas={_URL: "sha1"}, base_keys={_URL: "x/y@main"})
        self.rig = PoolRig(_MERGE_FLOW, clock=self.clock, github=self.github)
        self.item = self.rig.new_item("Login")
        self.run = plant_pr(self.rig.store, self.item, _URL, phase="code", branch=_BRANCH)
        self.gate = self.rig.store.create_step(stage="ready-merge", role="human", item=self.item)
        self.github.merge(_URL)

    def tick_until_crash(self, limit=20):
        for _ in range(limit):
            try:
                self.rig.tick()
            except PoolCrash:
                return True
            self.clock.advance(5)
        return False

    def gate_state(self):
        return self.rig.store.get_node(self.gate).state


class TestStopInsideATransaction(unittest.TestCase):
    def test_a_stop_inside_close_run_leaves_the_run_open_and_a_restart_resolves_it(self):
        fx = _MergedPrRig()
        crash = crash_on(fx.rig.store, "close_run")

        self.assertTrue(fx.tick_until_crash())

        self.assertTrue(crash.fired)
        self.assertTrue(fx.rig.store.get_run(fx.run).is_open)
        self.assertNotEqual(fx.gate_state(), State.DONE)

        fx.rig.restart()
        fx.rig.run(120, every=5, until=lambda: fx.gate_state() == State.DONE)

        self.assertEqual(fx.gate_state(), State.DONE)
        self.assertEqual(fx.rig.store.get_run(fx.run).state, "merged")


class TestStopBetweenTwoUseCases(unittest.TestCase):
    def test_a_stop_before_the_monitor_leaves_a_merge_unresolved_until_a_restart(self):
        fx = _MergedPrRig()
        fx.rig.crash_before_gate("monitor", nth=1)
        with self.assertRaises(PoolCrash):
            fx.rig.tick()

        self.assertNotEqual(fx.gate_state(), State.DONE)

        fx.rig.restart()
        fx.rig.run(60, every=5)

        self.assertEqual(fx.gate_state(), State.DONE)

    def test_a_stop_after_the_monitor_keeps_what_it_committed(self):
        fx = _MergedPrRig()
        fx.rig.crash_after_gate("monitor", nth=2)
        self.assertTrue(fx.tick_until_crash())

        self.assertEqual(fx.gate_state(), State.DONE)
        self.assertEqual(fx.rig.store.get_run(fx.run).state, "merged")


class TestRestart(unittest.TestCase):
    def test_restart_builds_a_new_tick_over_the_same_store_and_counts_it(self):
        rig = PoolRig(_MERGE_FLOW)
        before = rig.tick_use_case

        rig.restart()

        self.assertIsNot(rig.tick_use_case, before)
        self.assertEqual(rig.restarts, 1)
        rig.tick()


class TestSteppedPoll(unittest.TestCase):
    def test_a_stepped_poll_holds_its_closure_until_released(self):
        rig = PoolRig(_MERGE_FLOW, stepped_poll=True)
        self.assertIsInstance(rig.poll_runner, BlockingGithubPollRunner)

        rig.tick()
        rig.tick()

        self.assertEqual(rig.poll_runner.starts, 1)
        self.assertEqual(len(rig.poll_runner.pending), 1)

        rig.release_poll()

        self.assertEqual(rig.poll_runner.pending, [])


class TestScriptPastATick(unittest.TestCase):
    def setUp(self):
        self.clock = SimClock()
        self.rig = ScriptRig()
        self.runner = FakeScriptRunner(self.clock)
        self.rig.runner = self.runner
        self.rig.gate = ScriptStageUseCase(
            self.rig.store, self.rig.gate._flow_service, self.rig.gate._config,
            self.rig.gate._source, self.rig.gate._lifecycle, self.runner,
            ParkStepUseCase(self.rig.store), self.rig.complete, self.rig.gate._worktrees)
        self.step = self.rig.step()

    def state(self):
        return self.rig.store.get_node(self.step).state

    def test_a_script_stays_queued_across_ticks_and_finishes_after_its_delay(self):
        self.rig.gate.execute(self.clock())
        self.runner.finish_after(self.rig.key(self.step), 30, done())

        self.clock.advance(29)
        self.rig.gate.execute(self.clock())
        self.assertEqual(self.state(), State.QUEUED)
        self.clock.advance(1)
        self.rig.gate.execute(self.clock())

        self.assertEqual(self.state(), State.DONE)

    def test_a_killed_script_parks_the_step_naming_the_signal_exit(self):
        self.rig.gate.execute(self.clock())
        self.runner.kill(self.rig.key(self.step))

        self.rig.gate.execute(self.clock())

        node = self.rig.store.get_node(self.step)
        self.assertEqual(node.state, State.WAITING)
        self.assertIn("exited -15", node.park.reason or "")

    def test_a_script_that_outlives_the_pool_is_not_started_twice(self):
        self.rig.gate.execute(self.clock())
        self.runner.orphan_running()

        self.rig.gate.execute(self.clock())

        self.assertEqual(len(self.runner.started), 1)
        self.assertEqual(self.runner.orphaned(), [self.rig.key(self.step)])

        self.runner.kill_orphan(self.rig.key(self.step))
        self.rig.gate.execute(self.clock())

        self.assertEqual(len(self.runner.started), 2)

    def test_a_stop_after_poll_consumed_the_result_runs_the_stage_again(self):
        self.rig.gate.execute(self.clock())
        self.runner.finish(self.rig.key(self.step), done())
        crash_on(self.runner, "poll", when="after")

        with self.assertRaises(PoolCrash):
            self.rig.gate.execute(self.clock())

        self.assertEqual(self.state(), State.QUEUED)
        self.runner.orphan_running()
        self.rig.gate.execute(self.clock())

        self.assertEqual(len(self.runner.started), 2)

    def test_a_killed_result_carries_the_negative_signal_as_its_exit_code(self):
        self.rig.gate.execute(self.clock())

        self.runner.kill(self.rig.key(self.step), signal=9)

        self.assertEqual(self.runner.poll(self.rig.key(self.step)).exit_code, -9)
