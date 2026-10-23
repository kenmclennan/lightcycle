import datetime
import unittest
import unicodedata

from lightcycle.adapters.tui.footer import DashboardFooter, HealthIcon
from lightcycle.adapters.tui.hub import NodeHubScreen, TextArtifactViewerScreen
from lightcycle.domain.pool import HEALTH_IMAGE_IDS, HEALTH_IMAGE_STATES, TickTiming
from lightcycle.domain.pool.health_icon import PLACEHOLDER
from lightcycle.domain.work.artifact import Artifact
from tests.support.fake_fs import FakeFs
from tests.support.fake_health_icon import FakeHealthIcon
from tests.support.fake_store import FakeStore
from tests.support.fake_tick_timing_status import FakeTickTimingStatus
from tests.support.step_factory import create_owned_step
from tests.support.png_bytes import png_bytes
from tests.support.tui_harness import FakeLock, launch, make_test_container

NOW = datetime.datetime(2026, 1, 1, 12, 0, 0)
PID = 4242


def _timing(finished_ago=5.0):
    now = NOW.timestamp()
    return TickTiming(PID, now - finished_ago, ((now - finished_ago, 1.0),))


def _container(on=True, states=HEALTH_IMAGE_STATES, running=True, finished_ago=5.0, store=None):
    fs = FakeFs()
    icon = FakeHealthIcon()
    container = make_test_container(
        store=store, fs=fs, health_icon=icon, health_icons=on,
        lock=FakeLock(running=running, pid=PID),
        tick_timing_status=FakeTickTimingStatus(_timing(finished_ago)))
    for state in states:
        fs._files[container.config.tui_health_icon_path(state)] = png_bytes()
    return container, icon


def _frame_rows(session):
    strips = session.run(lambda: session.app.screen._compositor.render_strips())
    return list(strips)[-4:-1]


def _text(strip):
    return "".join(segment.text for segment in strip)


def _inner(strip):
    return _text(strip)[1:]


def _icon_colour(strip):
    for segment in strip:
        if PLACEHOLDER in segment.text:
            return segment.style.color.get_truecolor()
    return None


def _colour_id(colour):
    return colour.red << 16 | colour.green << 8 | colour.blue


def _frame(session):
    return [_text(s) for s in _frame_rows(session)]


class TestFooterHealthIconOff(unittest.TestCase):
    def test_footer_has_two_children_and_no_icon(self):
        container, icon = _container(on=False)
        session = launch(container, now=lambda: NOW)
        self.addCleanup(session.close)
        footer = session.app.screen.query_one(DashboardFooter)
        self.assertEqual(len(footer.children), 2)
        self.assertEqual(len(session.app.screen.query(HealthIcon)), 0)
        self.assertEqual(icon.transmitted, [])
        self.assertNotIn(PLACEHOLDER, "".join(_frame(session)))


class TestFooterHealthIconOn(unittest.TestCase):
    def _session(self, **kwargs):
        container, icon = _container(**kwargs)
        session = launch(container, now=lambda: NOW)
        self.addCleanup(session.close)
        return session, icon

    def test_icon_sits_at_the_left_edge_of_both_footer_rows(self):
        session, icon = self._session()
        rows = _frame_rows(session)
        status_row, shortcut_row = rows[1], rows[2]
        self.assertTrue(_inner(status_row).startswith(PLACEHOLDER))
        self.assertTrue(_inner(shortcut_row).startswith(PLACEHOLDER))
        self.assertEqual(_text(status_row).count(PLACEHOLDER), 3)
        self.assertIn("pool running", _text(status_row))
        self.assertEqual(_colour_id(_icon_colour(status_row)), HEALTH_IMAGE_IDS["0"])

    def test_one_blank_cell_separates_the_icon_from_both_rows_text(self):
        session, icon = self._session()
        rows = _frame_rows(session)
        for row, text in ((rows[1], "\u25cf pool running"), (rows[2], "\u2191\u2193 move")):
            cells = "".join(c for c in _inner(row) if not unicodedata.combining(c))
            self.assertTrue(cells.startswith(PLACEHOLDER * 3 + " " + text), cells[:30])

    def test_stalled_pool_shows_the_four_image(self):
        session, icon = self._session(finished_ago=500)
        self.assertEqual(_colour_id(_icon_colour(_frame_rows(session)[1])), HEALTH_IMAGE_IDS["4"])

    def test_stopped_pool_shows_the_four_image(self):
        session, icon = self._session(running=False)
        self.assertEqual(_colour_id(_icon_colour(_frame_rows(session)[1])), HEALTH_IMAGE_IDS["4"])

    def test_queued_item_selects_the_busy_image(self):
        store = FakeStore()
        create_owned_step(store, "queued", stage="build", role="agent")
        session, icon = self._session(store=store)
        self.assertEqual(_colour_id(_icon_colour(_frame_rows(session)[1])), HEALTH_IMAGE_IDS["busy"])

    def test_missing_image_renders_the_same_frame_as_feature_off(self):
        off_container, _ = _container(on=False)
        off = launch(off_container, now=lambda: NOW)
        self.addCleanup(off.close)
        session, icon = self._session(states=())
        self.assertEqual(_frame(session), _frame(off))
        self.assertEqual(icon.transmitted, [])

    def test_hub_footer_shows_the_icon(self):
        store = FakeStore()
        item = store.create_item("Item", "a description")
        container, _ = _container(store=store)
        session = launch(container, now=lambda: NOW)
        self.addCleanup(session.close)
        screen = NodeHubScreen(container, item, session.app._now, initial_tab="outputs")
        session.run(lambda: session.app.push_screen(screen))
        session.pause()
        session.run(session.app._refresh_status_bar)
        session.pause()
        self.assertTrue(_inner(_frame_rows(session)[2]).startswith(PLACEHOLDER))

    def test_artifact_viewer_footer_shows_the_icon(self):
        container, _ = _container()
        session = launch(container, now=lambda: NOW)
        self.addCleanup(session.close)
        screen = TextArtifactViewerScreen(Artifact(type="log", value="hello"), "node-1", 1, 1)
        session.run(lambda: session.app.push_screen(screen))
        session.pause()
        session.run(session.app._refresh_status_bar)
        session.pause()
        self.assertTrue(_inner(_frame_rows(session)[2]).startswith(PLACEHOLDER))

    def test_unmount_deletes_the_transmitted_images(self):
        container, icon = _container()
        session = launch(container, now=lambda: NOW)
        self.assertGreater(len(icon.transmitted), 0)
        session.close()
        self.assertEqual(icon.deleted, 1)


class TestHealthPoolStateAgreesWithTheFooterLabel(unittest.TestCase):
    def _state_and_label(self, **kwargs):
        container, _ = _container(**kwargs)
        session = launch(container, now=lambda: NOW)
        self.addCleanup(session.close)
        return session

    def test_starting_matches_the_label(self):
        from textual.widgets import Static

        session = self._state_and_label(running=False)
        session.press("p")
        label = _text(session.app.screen.query_one("#status-pool", Static).render_line(0))
        self.assertIn("pool starting", label)
        self.assertEqual(session.app._health_pool_state(False, None), "starting")

    def test_timed_out_start_matches_the_label(self):
        from textual.widgets import Static

        session = self._state_and_label(running=False)
        session.press("p")
        session.app._pool_transition_expired = True
        session.run(session.app._refresh_status_bar)
        label = str(session.app.screen.query_one("#status-pool", Static).render())
        self.assertIn("pool start timed out", label)
        self.assertEqual(session.app._health_pool_state(False, None), "start-timed-out")

    def test_running_and_stopped_match_the_label(self):
        session = self._state_and_label()
        self.assertEqual(session.app._health_pool_state(True, None), "running")
        self.assertEqual(session.app._health_pool_state(False, None), "stopped")
