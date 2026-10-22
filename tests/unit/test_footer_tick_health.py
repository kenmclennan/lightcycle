import datetime
import unittest

from lightcycle.adapters.tui.design_system import COLOURS, FOOTER_GLYPHS
from lightcycle.domain.pool import TickTiming
from tests.support.fake_drain import FakeDrain
from tests.support.fake_tick_timing_status import FakeTickTimingStatus
from tests.support.fake_workers import FakeWorkers
from tests.support.tui_harness import FakeLock, launch, make_test_container
from tests.unit.test_hub_footer_pool_transition import _colour_of, _rendered_segment

NOW = datetime.datetime(2026, 1, 1, 12, 0, 0)
PID = 4242


def _timing(durations=(1.0,), finished_ago=5.0, pid=PID):
    now = NOW.timestamp()
    ticks = tuple((now - finished_ago - i, d) for i, d in enumerate(durations))
    return TickTiming(pid, now - finished_ago, ticks)


class TestFooterTickHealth(unittest.TestCase):
    def _segment(self, timing, running=True, drain=None, press=(), workers=None):
        container = make_test_container(
            lock=FakeLock(running=running, pid=PID),
            tick_timing_status=FakeTickTimingStatus(timing),
            drain=drain, workers=workers)
        session = launch(container, now=lambda: NOW)
        self.addCleanup(session.close)
        for key in press:
            session.press(key)
        _, text, style = _rendered_segment(session, "#status-pool")
        return text, style

    def test_lagging_shows_the_median_in_amber(self):
        text, style = self._segment(_timing([9.0, 9.0, 9.0, 1.0]))
        self.assertEqual(text, "%s pool lagging · 9s ticks (p)" % FOOTER_GLYPHS["pool-lagging"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["amber"].lower())

    def test_stalled_shows_minutes_in_red(self):
        text, style = self._segment(_timing(finished_ago=185))
        self.assertEqual(text, "%s pool stalled · 3m (p)" % FOOTER_GLYPHS["pool-stalled"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["red"].lower())

    def test_stalled_wins_over_lagging(self):
        text, _ = self._segment(_timing([9.0, 9.0, 9.0, 1.0], finished_ago=200))
        self.assertIn("pool stalled", text)

    def test_start_transition_wins_over_a_stalled_file(self):
        text, _ = self._segment(_timing(finished_ago=500), running=False, press=("p",))
        self.assertEqual(text, "%s pool starting (p)" % FOOTER_GLYPHS["pool-starting"].glyph)

    def test_stop_transition_wins_over_a_stalled_file(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 0}], alive_pids=(1,))
        text, _ = self._segment(
            _timing(finished_ago=500), press=("p", "enter"), workers=workers)
        self.assertEqual(text, "%s pool stopping (p)" % FOOTER_GLYPHS["pool-stopping"].glyph)

    def test_drain_label_wins_over_a_stalled_file(self):
        text, _ = self._segment(_timing(finished_ago=500), drain=FakeDrain(requested=True))
        self.assertIn("pool draining", text)

    def test_a_stopped_pool_ignores_a_stalled_file(self):
        text, _ = self._segment(_timing(finished_ago=500), running=False)
        self.assertEqual(text, "%s pool not running (p)" % FOOTER_GLYPHS["pool-stopped"].glyph)

    def test_a_missing_file_shows_plain_pool_running(self):
        text, _ = self._segment(None)
        self.assertEqual(text, "%s pool running (p)" % FOOTER_GLYPHS["pool-running"].glyph)

    def test_another_pids_file_shows_plain_pool_running(self):
        text, _ = self._segment(_timing(finished_ago=500, pid=1))
        self.assertEqual(text, "%s pool running (p)" % FOOTER_GLYPHS["pool-running"].glyph)

    def test_glyphs_and_colours(self):
        self.assertEqual(tuple(FOOTER_GLYPHS["pool-lagging"]), ("◐", "amber"))
        self.assertEqual(tuple(FOOTER_GLYPHS["pool-stalled"]), ("⊘", "red"))
