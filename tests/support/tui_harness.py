import asyncio
import contextvars

from lightcycle.config import Config
from lightcycle.container import Container
from lightcycle.adapters.tui.app import LightcycleApp
from tests.support.fake_store import FakeStore


class FakeLock:
    def __init__(self, running=False):
        self._running = running

    def is_running(self):
        return self._running

    def set_running(self, running):
        self._running = running


class FakeBreakerPort:
    def __init__(self, is_open=False, reset_at=None):
        self._state = {"open": is_open, "reset_at": reset_at}

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)


def make_test_container(store=None, lock=None, breaker=None):
    return Container(
        store=store or FakeStore(),
        lock=lock or FakeLock(running=False),
        breaker=breaker or FakeBreakerPort(),
        config=Config(environ={}),
    )


class TuiSession:
    def __init__(self, container, now=None):
        self.app = LightcycleApp(container, now=now) if now is not None else LightcycleApp(container)
        self._loop = asyncio.new_event_loop()
        self._ctx = contextvars.copy_context()
        self._run_test_cm = self.app.run_test()
        self.pilot = self._run(self._run_test_cm.__aenter__())

    def _run(self, coro):
        task = self._loop.create_task(coro, context=self._ctx)
        return self._loop.run_until_complete(task)

    def pause(self):
        self._run(self.pilot.pause())

    def poll_tick(self):
        self.app._refresh()
        self.pause()

    def resize(self, width, height):
        self._run(self.pilot.resize_terminal(width, height))

    def close(self):
        self._run(self._run_test_cm.__aexit__(None, None, None))
        self._loop.close()


def launch(container, now=None):
    session = TuiSession(container, now=now)
    session.pause()
    return session
