import unittest
from unittest.mock import patch

from lightcycle.adapters.tui.hub import NodeHubScreen
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.tui_harness import launch, make_test_container

LOG_PATH = "/fake/logs/worker.log"
WORKER_PID = 111


def _running_step():
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="coder", role="agent", parent=item)
    store.claim_ready("agent")
    workers = FakeWorkers(
        workers=[{"step": step, "role": "coder", "pid": WORKER_PID, "pid_started": None, "log": LOG_PATH}],
        alive_pids={WORKER_PID},
    )
    fs = FakeFs(files={LOG_PATH: b""})
    return store, item, step, fs, workers


def _render_hierarchy_spy():
    calls = []
    original = NodeHubScreen._render_hierarchy

    def spy(screen, *a, **kw):
        calls.append(1)
        return original(screen, *a, **kw)

    return calls, spy


class _HubTestCase(unittest.TestCase):
    def _launch(self, store=None, fs=None, workers=None):
        session = launch(make_test_container(store=store or FakeStore(), fs=fs, workers=workers))
        self.addCleanup(session.close)
        return session

    def _push_hub(self, session, node_id):
        session.run(
            lambda: session.app.push_screen(
                NodeHubScreen(session.app.container, node_id, session.app._now)
            )
        )
        session.pause()
        return session.app.screen


class TestNodeHubPollsOncePerInterval(_HubTestCase):
    def test_app_refresh_no_longer_forwards_into_the_hub_screen(self):
        store = FakeStore()
        item = store.create_item("item", "a description")
        session = self._launch(store)
        self._push_hub(session, item)

        calls, spy = _render_hierarchy_spy()
        with patch.object(NodeHubScreen, "_render_hierarchy", spy):
            session.run(session.app._refresh)
            session.pause()

        self.assertEqual(calls, [])

    def test_hub_own_poll_refresh_does_exactly_one_round_trip(self):
        store = FakeStore()
        item = store.create_item("item", "a description")
        session = self._launch(store)
        self._push_hub(session, item)

        calls, spy = _render_hierarchy_spy()
        with patch.object(NodeHubScreen, "_render_hierarchy", spy):
            session.run(session.app.screen.poll_refresh)
            session.pause()

        self.assertEqual(len(calls), 1)


class TestNodeHubSuspendedScreenTimersArePaused(_HubTestCase):
    def test_poll_and_log_timers_pause_on_suspend_and_resume_on_resume(self):
        store, item, step, fs, workers = _running_step()
        session = self._launch(store, fs=fs, workers=workers)
        first = self._push_hub(session, item)
        self.assertIsNotNone(first._poll_timer)
        self.assertIsNotNone(first._log_timer)

        self._push_hub(session, item)

        self.assertFalse(first._poll_timer._active.is_set())
        self.assertFalse(first._log_timer._active.is_set())

        session.run(session.app.pop_screen)
        session.pause()

        self.assertTrue(first._poll_timer._active.is_set())
        self.assertTrue(first._log_timer._active.is_set())

    def test_suspend_and_resume_do_not_raise_when_log_timer_is_none(self):
        store = FakeStore()
        item = store.create_item("plain item, no worker", "a description")
        session = self._launch(store)
        first = self._push_hub(session, item)
        self.assertIsNone(first._log_timer)

        self._push_hub(session, item)
        self.assertFalse(first._poll_timer._active.is_set())

        session.run(session.app.pop_screen)
        session.pause()

        self.assertTrue(first._poll_timer._active.is_set())


if __name__ == "__main__":
    unittest.main()
