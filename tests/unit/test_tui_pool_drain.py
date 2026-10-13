import unittest

from lightcycle.adapters.tui.design_system import FOOTER_GLYPHS
from tests.support.fake_drain import FakeDrain
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.screen_render import _plain_row, render
from tests.support.tui_harness import FakeLock, launch, make_test_container


def _workers(n):
    return FakeWorkers(
        workers=[{"spawnid": "w%d" % i, "pid": i + 1, "started": 0} for i in range(n)],
        alive_pids=tuple(range(1, n + 1)),
    )


def _frame(session):
    strips = session.run(lambda: session.app.screen._compositor.render_strips())
    return "\n".join(_plain_row(strip) for strip in strips)


def _session(test, drain, running=True, workers=3):
    session = launch(make_test_container(
        store=FakeStore(), lock=FakeLock(running=running), drain=drain, workers=_workers(workers),
    ))
    test.addCleanup(session.close)
    return session


class TestDrainingFooter(unittest.TestCase):
    def test_footer_renders_the_draining_label_count_and_glyph(self):
        frame = render("priority-list#pool-draining")

        self.assertIn(
            "%s pool draining (3 running)" % FOOTER_GLYPHS["pool-draining"].glyph, frame
        )
        self.assertNotIn("pool running", frame)

    def test_footer_is_unchanged_when_not_draining(self):
        session = _session(self, FakeDrain())

        frame = _frame(session)

        self.assertIn("pool running", frame)
        self.assertNotIn("draining", frame)

    def test_a_stale_marker_with_no_pool_renders_not_running(self):
        session = _session(self, FakeDrain(requested=True), running=False)

        frame = _frame(session)

        self.assertIn("pool not running", frame)
        self.assertNotIn("draining", frame)

    def test_a_stop_transition_outranks_draining(self):
        session = _session(self, FakeDrain(requested=True))

        session.press("p")
        session.press("enter")
        frame = _frame(session)

        self.assertIn("pool stopping", frame)
        self.assertNotIn("pool draining", frame)

    def test_the_draining_footer_wraps_nothing_at_a_narrow_width(self):
        narrow = render("priority-list#pool-draining", size=(80, 30))
        wide = render("priority-list#pool-draining", size=(140, 30))

        self.assertIn("pool draining (3 running)", narrow)
        self.assertIn("pool draining (3 running)", wide)


class TestPoolPromptDrainOption(unittest.TestCase):
    def test_prompt_offers_drain_when_running_and_not_draining(self):
        session = _session(self, FakeDrain())

        session.press("p")
        frame = _frame(session)

        self.assertIn("Stop the pool", frame)
        self.assertIn("Drain: finish running work, then stop", frame)

    def test_prompt_omits_drain_when_already_draining(self):
        session = _session(self, FakeDrain(requested=True))

        session.press("p")
        frame = _frame(session)

        self.assertIn("Stop the pool", frame)
        self.assertNotIn("Drain: finish running work", frame)

    def test_choosing_drain_requests_it_and_begins_no_transition(self):
        drain = FakeDrain()
        session = _session(self, drain)

        session.press("p")
        session.press("down")
        session.press("enter")

        self.assertTrue(drain.requested())
        self.assertEqual(drain.request_calls, 1)
        self.assertIsNone(session.app._pool_transition_kind)


if __name__ == "__main__":
    unittest.main()
