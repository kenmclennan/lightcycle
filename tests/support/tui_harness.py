import asyncio
import contextvars

from lightcycle import __version__
from lightcycle.application.setup import UpgradeResponse
from lightcycle.config import Config
from lightcycle.container import Container
from lightcycle.adapters.tui.app import LightcycleApp
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers


def _no_upgrade_available():
    return UpgradeResponse(current=__version__, remote=__version__, available=False, applied=False)


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


def make_test_container(store=None, lock=None, breaker=None, fs=None, workers=None):
    return Container(
        store=store or FakeStore(),
        lock=lock or FakeLock(running=False),
        breaker=breaker or FakeBreakerPort(),
        fs=fs or FakeFs(),
        workers=workers or FakeWorkers(),
        config=Config(environ={}),
    )


class TuiSession:
    def __init__(self, container, now=None, upgrade_check=None, size=None):
        self.app = LightcycleApp(container, now=now, upgrade_check=upgrade_check or _no_upgrade_available)
        self._loop = asyncio.new_event_loop()
        self._ctx = contextvars.copy_context()
        self._run_test_cm = self.app.run_test(size=size) if size else self.app.run_test()
        self.pilot = self._run(self._run_test_cm.__aenter__())

    def _run(self, coro):
        task = self._loop.create_task(coro, context=self._ctx)
        return self._loop.run_until_complete(task)

    def run(self, func):
        async def _call():
            return func()

        return self._run(_call())

    def press(self, key):
        self._run(self.pilot.press(key))
        self.pause()

    def pause(self):
        self._run(self.pilot.pause())

    def poll_tick(self):
        self.run(self.app._refresh)
        self.pause()

    def close(self):
        self._run(self._run_test_cm.__aexit__(None, None, None))
        self._loop.close()


def launch(container, now=None, upgrade_check=None, size=None):
    session = TuiSession(container, now=now, upgrade_check=upgrade_check, size=size)
    session.pause()
    return session
