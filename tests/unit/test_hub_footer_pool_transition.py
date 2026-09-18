import unittest
from unittest.mock import patch

from textual.widgets import Static

from lightcycle.adapters.tui.design_system import COLOURS, FOOTER_GLYPHS
from lightcycle.adapters.tui.hub import NodeHubScreen, TextArtifactViewerScreen
from lightcycle.application.pool.breaker_status import BreakerStatusUseCase
from lightcycle.application.pool.pool_hold_status import PoolHoldStatusUseCase
from lightcycle.application.pool.run_lock import PoolRunningUseCase
from lightcycle.domain.work.artifact import Artifact
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.tui_harness import FakeLock, launch, make_test_container


def _rendered_segment(session, widget_id):
    widget = session.app.screen.query_one(widget_id, Static)
    strip = widget.render_line(0)
    text = "".join(segment.text for segment in strip)
    style = None
    for segment in strip:
        if segment.text.strip():
            style = segment.style
            break
    return widget, text, style


def _colour_of(style):
    return style.color.get_truecolor().hex.lower()


class TestNodeHubFooterPoolTransition(unittest.TestCase):
    def _launch_with_hub(self, now=None, **kwargs):
        store = FakeStore()
        item = store.create_item("Item", "a description")
        session = launch(make_test_container(store=store, **kwargs), now=now)
        self.addCleanup(session.close)
        screen = NodeHubScreen(session.app.container, item, session.app._now, initial_tab="artifacts")
        session.run(lambda: session.app.push_screen(screen))
        session.pause()
        session.pause()
        return session

    def test_hub_footer_renders_plain_pool_text_unchanged(self):
        session = self._launch_with_hub(lock=FakeLock(running=True))

        _, text, _ = _rendered_segment(session, "#status-pool")
        self.assertEqual(text, "%s pool running (p)" % FOOTER_GLYPHS["pool-running"].glyph)

    def test_pressing_p_shows_starting_immediately_on_hub_footer(self):
        session = self._launch_with_hub(lock=FakeLock(running=False))

        session.press("p")

        _, text, style = _rendered_segment(session, "#status-pool")
        self.assertEqual(text, "%s pool starting (p)" % FOOTER_GLYPHS["pool-starting"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["amber"].lower())

    def test_confirming_stop_shows_stopping_immediately_on_hub_footer(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 0}], alive_pids=(1,))
        session = self._launch_with_hub(lock=FakeLock(running=True), workers=workers)

        session.press("p")
        session.press("enter")

        _, text, style = _rendered_segment(session, "#status-pool")
        self.assertEqual(text, "%s pool stopping (p)" % FOOTER_GLYPHS["pool-stopping"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["amber"].lower())

    def test_fast_poll_tick_clears_hub_footer_on_resolution(self):
        lock = FakeLock(running=False)
        session = self._launch_with_hub(lock=lock)

        session.press("p")
        lock.set_running(True)
        session.run(session.app._tick_pool_transition)
        session.pause()

        _, text, style = _rendered_segment(session, "#status-pool")
        self.assertEqual(text, "%s pool running (p)" % FOOTER_GLYPHS["pool-running"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["cyan"].lower())
        self.assertIsNone(session.app._pool_transition_timer)

    def test_hub_opened_mid_transition_shows_in_flight_state_on_mount(self):
        store = FakeStore()
        item = store.create_item("Item", "a description")
        session = launch(make_test_container(store=store, lock=FakeLock(running=False)))
        self.addCleanup(session.close)

        session.press("p")

        screen = NodeHubScreen(session.app.container, item, session.app._now, initial_tab="artifacts")
        session.run(lambda: session.app.push_screen(screen))
        session.pause()
        session.pause()

        _, text, style = _rendered_segment(session, "#status-pool")
        self.assertEqual(text, "%s pool starting (p)" % FOOTER_GLYPHS["pool-starting"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["amber"].lower())


class TestArtifactViewerFooterPoolTransition(unittest.TestCase):
    def _launch_with_viewer(self, now=None, **kwargs):
        session = launch(make_test_container(**kwargs), now=now)
        self.addCleanup(session.close)
        screen = TextArtifactViewerScreen(Artifact(type="log", value="hello"), "node-1", 1, 1)
        session.run(lambda: session.app.push_screen(screen))
        session.pause()
        session.pause()
        return session

    def test_artifact_viewer_no_longer_owns_a_poll_timer(self):
        session = self._launch_with_viewer()

        self.assertFalse(hasattr(session.app.screen, "poll_refresh"))

    def test_pressing_p_shows_starting_immediately_on_viewer_footer(self):
        session = self._launch_with_viewer(lock=FakeLock(running=False))

        session.press("p")

        _, text, style = _rendered_segment(session, "#status-pool")
        self.assertEqual(text, "%s pool starting (p)" % FOOTER_GLYPHS["pool-starting"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["amber"].lower())

    def test_fast_poll_tick_clears_viewer_footer_on_resolution(self):
        lock = FakeLock(running=False)
        session = self._launch_with_viewer(lock=lock)

        session.press("p")
        lock.set_running(True)
        session.run(session.app._tick_pool_transition)
        session.pause()

        _, text, style = _rendered_segment(session, "#status-pool")
        self.assertEqual(text, "%s pool running (p)" % FOOTER_GLYPHS["pool-running"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["cyan"].lower())
        self.assertIsNone(session.app._pool_transition_timer)


class TestRefreshStatusBarReadsOnce(unittest.TestCase):
    def test_each_use_case_executes_once_per_call_regardless_of_mounted_screen_count(self):
        store = FakeStore()
        item = store.create_item("Item", "a description")
        session = launch(make_test_container(store=store, lock=FakeLock(running=True)))
        self.addCleanup(session.close)

        hub = NodeHubScreen(session.app.container, item, session.app._now, initial_tab="artifacts")
        session.run(lambda: session.app.push_screen(hub))
        session.pause()
        session.pause()

        viewer = TextArtifactViewerScreen(Artifact(type="log", value="hello"), item, 1, 1)
        session.run(lambda: session.app.push_screen(viewer))
        session.pause()
        session.pause()

        calls = {"running": 0, "breaker": 0, "hold": 0}
        original_running = PoolRunningUseCase.execute
        original_breaker = BreakerStatusUseCase.execute
        original_hold = PoolHoldStatusUseCase.execute

        def _spy_running(self, *a, **kw):
            calls["running"] += 1
            return original_running(self, *a, **kw)

        def _spy_breaker(self, *a, **kw):
            calls["breaker"] += 1
            return original_breaker(self, *a, **kw)

        def _spy_hold(self, *a, **kw):
            calls["hold"] += 1
            return original_hold(self, *a, **kw)

        with patch.object(PoolRunningUseCase, "execute", _spy_running), \
                patch.object(BreakerStatusUseCase, "execute", _spy_breaker), \
                patch.object(PoolHoldStatusUseCase, "execute", _spy_hold):
            session.run(session.app._refresh_status_bar)

        self.assertEqual(calls, {"running": 1, "breaker": 1, "hold": 1})
