import io
import signal
import unittest
from contextlib import redirect_stdout
from unittest import mock

import lightcycle.cli as cli_mod
from lightcycle.adapters import stop_signal
from lightcycle.adapters.stop_signal import StopSignal
from tests.unit.test_drain import _StartContainer, _tick_result
from tests.support.fake_drain import FakeDrain


class TestStopSignalHandle(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(stop_signal.os, "write")
        self.write = patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_first_sigterm_sets_requested_and_acknowledges_once(self):
        stop = StopSignal()
        stop.handle(signal.SIGTERM)
        stop.handle(signal.SIGTERM)
        self.assertTrue(stop.requested)
        self.write.assert_called_once()
        fd, text = self.write.call_args[0]
        self.assertEqual(fd, 2)
        self.assertIn(b"finishing the current tick", text)
        self.assertIn(b"Ctrl-C again", text)

    def test_a_second_sigint_raises(self):
        stop = StopSignal()
        stop.handle(signal.SIGINT)
        with self.assertRaises(KeyboardInterrupt):
            stop.handle(signal.SIGINT)

    def test_a_signal_in_the_sleep_window_raises_without_acknowledging(self):
        stop = StopSignal()

        def interrupted(seconds):
            stop.handle(signal.SIGTERM)

        with mock.patch.object(stop_signal.time, "sleep", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                stop.pause(5)
        self.write.assert_not_called()
        self.assertFalse(stop.requested)

    def test_pause_does_not_sleep_once_requested(self):
        stop = StopSignal()
        stop.handle(signal.SIGTERM)
        with mock.patch.object(stop_signal.time, "sleep") as sleep:
            stop.pause(5)
        sleep.assert_not_called()

    def test_the_window_closes_after_pause_raises(self):
        stop = StopSignal()

        def interrupted(seconds):
            raise KeyboardInterrupt

        with mock.patch.object(stop_signal.time, "sleep", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                stop.pause(5)
        stop.handle(signal.SIGTERM)
        self.assertTrue(stop.requested)


class TestCmdStartHonoursStop(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))
        self.events = []
        self.ticks = 0
        self.stopped = 0

    def _start(self, signals, sleep_signals=()):
        cli_mod.set_container(_StartContainer(FakeDrain()))
        handlers = {}

        def register(signum, handler):
            handlers[signum] = handler

        def fake_run_tick(tick, worker_log, tick_input, now):
            self.ticks += 1
            if self.ticks > 1:
                raise AssertionError("a second tick ran")
            for signum in signals:
                handlers[signum](signum, None)
            self.events.append("tick")
            return _tick_result(0, False)

        def fake_stop_pool():
            self.stopped += 1
            return []

        def fake_write(fd, data):
            self.events.append("ack")

        def fake_sleep(seconds):
            self.events.append("sleep")
            for signum in sleep_signals:
                handlers[signum](signum, None)

        out = io.StringIO()
        with mock.patch.object(cli_mod, "require_store", lambda: True), \
                mock.patch.object(cli_mod, "_flow", lambda: None), \
                mock.patch.object(cli_mod, "_run_tick", fake_run_tick), \
                mock.patch.object(cli_mod, "_stop_pool", fake_stop_pool), \
                mock.patch.object(cli_mod, "_format_tick", lambda r, p, n: ([], None)), \
                mock.patch.object(cli_mod, "_upgrade_notice_lines", lambda r: []), \
                mock.patch.object(cli_mod, "UpgradeCadenceUseCase"), \
                mock.patch.object(cli_mod.signal, "signal", register), \
                mock.patch.object(stop_signal.os, "write", fake_write), \
                mock.patch.object(stop_signal.time, "sleep", fake_sleep), \
                redirect_stdout(out):
            rc = cli_mod.cmd_start([])
        return rc, out.getvalue()

    def test_a_sigterm_during_a_tick_lets_it_finish_and_ends_the_loop_after_it(self):
        rc, out = self._start([signal.SIGTERM])
        self.assertEqual((rc, self.ticks, self.stopped), (0, 1, 1))
        self.assertEqual(self.events, ["ack", "tick"])
        self.assertNotIn("sleep", self.events)
        self.assertIn("lc start stopping", out)

    def test_a_repeated_sigterm_acknowledges_once(self):
        rc, _ = self._start([signal.SIGTERM, signal.SIGTERM])
        self.assertEqual(rc, 0)
        self.assertEqual(self.events.count("ack"), 1)

    def test_a_second_sigint_during_a_tick_forces_the_stop_path(self):
        rc, out = self._start([signal.SIGINT, signal.SIGINT])
        self.assertEqual((rc, self.stopped), (0, 1))
        self.assertNotIn("tick", self.events)
        self.assertIn("lc start stopping", out)

    def test_a_sigterm_in_the_sleep_window_stops_without_another_tick_or_acknowledgement(self):
        rc, out = self._start([], sleep_signals=[signal.SIGTERM])
        self.assertEqual((rc, self.ticks, self.stopped), (0, 1, 1))
        self.assertNotIn("ack", self.events)
        self.assertIn("lc start stopping", out)
