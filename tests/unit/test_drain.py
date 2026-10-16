import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import lightcycle.cli as cli_mod
from lightcycle.application.pool import (
    ClearDrainUseCase,
    DrainPoolUseCase,
    PoolDrainStatus,
    PoolDrainStatusUseCase,
)
from lightcycle.application.pool.pool_control import DRAIN_SLOW_SECONDS
from tests.support.fake_drain import FakeDrain
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.tui_harness import FakeLock


class _UnreadableWorkers(FakeWorkers):
    def workers_state(self):
        from lightcycle.ports.workers import RegistryUnreadable

        raise RegistryUnreadable("boom")


def _workers(n):
    return FakeWorkers(
        workers=[{"spawnid": "w%d" % i, "pid": i + 1, "started": 0} for i in range(n)],
        alive_pids=tuple(range(1, n + 1)),
    )


def _status(drain, workers, store=None):
    return PoolDrainStatusUseCase(drain, workers, store if store is not None else FakeStore())


def _store_with(*specs):
    store = FakeStore()
    item = store.create_item("t", "d")
    for role, state in specs:
        sid = store.create_step(step="poll-ci", role=role, parent=item)
        store.update_state(sid, state)
    return store


class TestDrainPoolUseCase(unittest.TestCase):
    def test_no_pool_writes_nothing(self):
        drain = FakeDrain()
        resp = DrainPoolUseCase(FakeLock(running=False), drain).execute()
        self.assertEqual(resp.outcome, "no-pool")
        self.assertFalse(drain.requested())
        self.assertEqual(drain.request_calls, 0)

    def test_requests_a_drain_of_a_running_pool(self):
        drain = FakeDrain()
        resp = DrainPoolUseCase(FakeLock(running=True, pid=77), drain).execute()
        self.assertEqual((resp.outcome, resp.pid), ("requested", 77))
        self.assertTrue(drain.requested())

    def test_already_draining_does_not_request_again(self):
        drain = FakeDrain(requested=True)
        resp = DrainPoolUseCase(FakeLock(running=True), drain).execute()
        self.assertEqual(resp.outcome, "already-draining")
        self.assertEqual(drain.request_calls, 0)


class TestPoolDrainStatusUseCase(unittest.TestCase):
    def test_draining_only_when_the_pool_runs_and_the_marker_is_set(self):
        status = _status(FakeDrain(requested=True), _workers(3))
        self.assertTrue(status.execute(True, 0).draining)
        self.assertFalse(status.execute(False, 0).draining)
        self.assertFalse(_status(FakeDrain(), _workers(3)).execute(True, 0).draining)

    def test_running_is_the_live_worker_count(self):
        status = _status(FakeDrain(requested=True), _workers(3)).execute(True, 0)
        self.assertEqual(status.running, 3)

    def test_a_stale_marker_with_no_pool_reports_zero_running(self):
        status = _status(FakeDrain(requested=True), _workers(3)).execute(False, 0)
        self.assertEqual((status.draining, status.running), (False, 0))

    def test_an_unreadable_registry_reports_zero_running_without_raising(self):
        status = _status(FakeDrain(requested=True), _UnreadableWorkers()).execute(True, 0)
        self.assertEqual((status.draining, status.running), (True, 0))


class TestPoolDrainWaitsForEngineSteps(unittest.TestCase):
    def _run(self, specs, workers=0, at=None, now=0):
        drain = FakeDrain(requested=True, at=at)
        return _status(drain, _workers(workers), _store_with(*specs)).execute(True, now)

    def test_a_queued_engine_step_is_waited_for(self):
        status = self._run([("engine", "queued")])
        self.assertEqual((status.running, status.engine_steps), (0, 1))
        self.assertEqual(status.waiting_text(), "0 workers, 1 engine step")

    def test_a_running_engine_step_is_waited_for(self):
        self.assertEqual(self._run([("engine", "running")]).engine_steps, 1)

    def test_human_gates_and_agent_steps_are_not_waited_for(self):
        status = self._run([("human", "waiting"), ("agent", "queued"), ("engine", "done")])
        self.assertEqual(status.engine_steps, 0)

    def test_workers_and_engine_steps_are_both_named(self):
        status = self._run([("engine", "queued")], workers=1)
        self.assertEqual(status.waiting_text(), "1 worker, 1 engine step")

    def test_a_drain_older_than_the_bound_is_slow_and_says_so(self):
        status = self._run([("engine", "queued")], at=0, now=DRAIN_SLOW_SECONDS + 1)
        self.assertTrue(status.slow)
        self.assertTrue(status.waiting_text().endswith(" - slow"))

    def test_a_drain_within_the_bound_is_not_slow(self):
        self.assertFalse(self._run([("engine", "queued")], at=0, now=DRAIN_SLOW_SECONDS).slow)


class TestClearDrainUseCase(unittest.TestCase):
    def test_clears_the_marker_and_tolerates_none(self):
        drain = FakeDrain(requested=True)
        ClearDrainUseCase(drain).execute()
        ClearDrainUseCase(drain).execute()
        self.assertFalse(drain.requested())


class _Container:
    def __init__(self, lock, drain, workers=None):
        self.lock = lock
        self.drain = drain
        self.workers = workers if workers is not None else FakeWorkers()


class TestCmdStopDrain(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _run(self, container, *argv):
        cli_mod.set_container(container)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_mod.cmd_stop(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_drain_requested_prints_the_pid_and_returns_zero(self):
        drain = FakeDrain()
        rc, out, _ = self._run(_Container(FakeLock(running=True, pid=42), drain), "--drain")
        self.assertEqual(rc, 0)
        self.assertEqual(
            out.strip(),
            "lc stop --drain asked pid 42 to drain - it exits when its running workers and engine steps finish",
        )
        self.assertTrue(drain.requested())

    def test_drain_on_a_draining_pool_says_so_and_writes_nothing(self):
        drain = FakeDrain(requested=True)
        rc, out, _ = self._run(_Container(FakeLock(running=True), drain), "--drain")
        self.assertEqual((rc, out.strip()), (0, "pool already draining"))
        self.assertEqual(drain.request_calls, 0)

    def test_drain_with_no_pool_refuses_on_stderr(self):
        drain = FakeDrain()
        rc, out, err = self._run(_Container(FakeLock(running=False), drain), "--drain")
        self.assertEqual((rc, out, err), (1, "", "no pool running\n"))
        self.assertFalse(drain.requested())

    def test_plain_stop_signals_the_pool_and_never_touches_the_marker(self):
        drain = FakeDrain()
        workers = FakeWorkers()
        rc, out, _ = self._run(_Container(FakeLock(running=True, pid=42), drain, workers))
        self.assertEqual((rc, out.strip()), (0, "lc stop signalled pid 42"))
        self.assertEqual(workers.killed, [42])
        self.assertFalse(drain.requested())

    def test_stop_help_lists_drain(self):
        with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
            cli_mod.cmd_stop(["--help"])
        self.assertIn("--drain", out.getvalue())


class TestDrainProgressLines(unittest.TestCase):
    def test_prints_on_the_first_tick_and_on_each_change_only(self):
        last = None
        printed = []
        statuses = [
            PoolDrainStatus(True, 5), PoolDrainStatus(True, 5), PoolDrainStatus(True, 1, 1),
            PoolDrainStatus(True, 1, 1), PoolDrainStatus(True, 1, 1, slow=True),
        ]
        for status in statuses:
            lines, last = cli_mod._drain_progress_lines(status, last)
            printed.extend(lines)
        self.assertEqual(
            printed,
            [
                "lc start draining - waiting for 5 workers",
                "lc start draining - waiting for 1 worker, 1 engine step",
                "lc start draining - waiting for 1 worker, 1 engine step - slow",
            ],
        )


class _Config:
    def poll_seconds(self):
        return 0

    def max_agents(self):
        return 5

    def tick_failure_cap(self):
        return 3

    def pool_upgrade_check_seconds(self):
        return 3600


class _StartContainer:
    def __init__(self, drain, workers=None, store=None):
        self.store = store if store is not None else FakeStore()
        self.lock = FakeLock(running=False)
        self.drain = drain
        self.workers = workers if workers is not None else FakeWorkers()
        self.config = _Config()
        self.worker_log = None
        self.upgrade = None
        self.ticked = 0

    def tick(self, flow=None):
        return object()


class TestCmdStartDrainLoop(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))
        self.stopped = 0
        self.inputs = []

    def _start(
        self, container, alive_by_tick, interrupt_after=None, request_on_first=False, on_tick=None
    ):
        cli_mod.set_container(container)
        sequence = iter(alive_by_tick)

        def fake_run_tick(tick, worker_log, tick_input, now):
            self.inputs.append(tick_input)
            if on_tick is not None:
                on_tick()
            if request_on_first and len(self.inputs) == 1:
                container.drain.request()
            if interrupt_after is not None and len(self.inputs) > interrupt_after:
                raise KeyboardInterrupt
            return _tick_result(next(sequence), tick_input.drain)

        def fake_stop_pool():
            self.stopped += 1
            return ["stopped"]

        out = io.StringIO()
        with mock.patch.object(cli_mod, "require_store", lambda: True),                 mock.patch.object(cli_mod, "_flow", lambda: None),                 mock.patch.object(cli_mod, "_run_tick", fake_run_tick),                 mock.patch.object(cli_mod, "_stop_pool", fake_stop_pool),                 mock.patch.object(cli_mod, "_format_tick", lambda r, p, n: ([], None)),                 mock.patch.object(cli_mod, "_upgrade_notice_lines", lambda r: []),                 mock.patch.object(cli_mod, "UpgradeCadenceUseCase"),                 mock.patch.object(cli_mod.signal, "signal"),                 mock.patch.object(cli_mod.time, "sleep"),                 redirect_stdout(out):
            rc = cli_mod.cmd_start([])
        return rc, out.getvalue()

    def test_exits_on_the_tick_reporting_zero_not_on_the_tick_reporting_one(self):
        drain = FakeDrain()
        rc, out = self._start(_StartContainer(drain), [5, 5, 1, 0], request_on_first=True)
        self.assertEqual(rc, 0)
        self.assertEqual([i.drain for i in self.inputs], [False, True, True, True])
        self.assertEqual(self.stopped, 1)
        self.assertEqual(
            [l for l in out.splitlines() if "drain" in l],
            [
                "lc start draining - waiting for 5 workers",
                "lc start draining - waiting for 1 worker",
                "lc start draining - waiting for 0 workers",
                "lc start drained - no workers or engine steps running, stopping",
            ],
        )

    def test_exits_on_the_first_drain_tick_when_nothing_is_alive(self):
        rc, _ = self._start(_StartContainer(FakeDrain()), [3, 0], request_on_first=True)
        self.assertEqual((rc, len(self.inputs)), (0, 2))

    def test_keeps_ticking_while_an_engine_step_is_in_flight_then_stops(self):
        store = _store_with(("engine", "queued"))
        drain = FakeDrain()
        container = _StartContainer(drain, store=store)

        def finish_engine_step_on_third_tick(*_):
            if len(self.inputs) == 4:
                store.update_state(store.all_steps()[0].id, "done")

        rc, out = self._start(
            container, [0, 0, 0, 0, 0], request_on_first=True, on_tick=finish_engine_step_on_third_tick
        )
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.inputs), 4)
        self.assertEqual(self.stopped, 1)
        self.assertIn("lc start draining - waiting for 0 workers, 1 engine step", out)

    def test_stops_at_once_when_only_human_gates_are_open(self):
        container = _StartContainer(FakeDrain(), store=_store_with(("human", "waiting")))
        rc, _ = self._start(container, [0, 0], request_on_first=True)
        self.assertEqual((rc, len(self.inputs)), (0, 2))

    def test_clears_a_stale_marker_when_it_takes_the_lock_and_does_not_drain(self):
        drain = FakeDrain(requested=True)
        self._start(_StartContainer(drain), [0], interrupt_after=0)
        self.assertFalse(drain.requested())
        self.assertFalse(self.inputs[0].drain)

    def test_clears_the_marker_after_an_interrupt_during_a_drain(self):
        drain = FakeDrain()
        rc, _ = self._start(_StartContainer(drain), [3], interrupt_after=1, request_on_first=True)
        self.assertEqual(rc, 0)
        self.assertEqual(self.stopped, 1)
        self.assertFalse(drain.requested())


def _tick_result(alive, draining):
    class Pool:
        pass

    class Result:
        pass

    pool = Pool()
    pool.alive = alive
    pool.draining = draining
    result = Result()
    result.pool = pool
    return result


if __name__ == "__main__":
    unittest.main()
