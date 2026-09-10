import asyncio
import contextvars
import os
import shutil
import tempfile

from lightcycle import __version__
from lightcycle.application.setup import UpgradeResponse
from lightcycle.adapters.backup import SqliteBackupAdapter
from lightcycle.adapters.breaker import BreakerAdapter
from lightcycle.adapters.fsio import FsAdapter
from lightcycle.adapters.github import GitHubEventsAdapter
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.adapters.launcher import LauncherAdapter
from lightcycle.adapters.lock import RunLockAdapter
from lightcycle.adapters.scaffold import ScaffoldAdapter
from lightcycle.adapters.spawner import SpawnerAdapter
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.adapters.worker_log import WorkerLogAdapter
from lightcycle.adapters.workers import WorkersAdapter
from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter
from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.config import Config, _SEED_KEYS
from lightcycle.container import Container
from lightcycle.ports.backup import BackupPort
from lightcycle.ports.git import GitPort
from lightcycle.ports.scaffold import ScaffoldPort
from lightcycle.adapters.tui.app import LightcycleApp
from lightcycle.adapters.tui.design_system import ACTIVE_GLYPH_REST_INDEX
from lightcycle.adapters.tui.hub import NodeHubScreen
from tests.support.fake_fs import FakeFs
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers


def _no_upgrade_available():
    return UpgradeResponse(current=__version__, remote=__version__, available=False, applied=False)


class FakeLock:
    def __init__(self, running=False, pid=4242):
        self._running = running
        self._pid = pid

    def is_running(self):
        return self._running

    def holder_pid(self):
        return self._pid if self._running else None

    def set_running(self, running):
        self._running = running


class FakeBreakerPort:
    def __init__(self, is_open=False, reset_at=None):
        self._state = {"open": is_open, "reset_at": reset_at}

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)


class FakeLauncher:
    def __init__(self, url_succeeds=True, path_succeeds=True):
        self.url_succeeds = url_succeeds
        self.path_succeeds = path_succeeds
        self.opened_urls = []
        self.opened_paths = []

    def open_url(self, url):
        self.opened_urls.append(url)
        return self.url_succeeds

    def open_path(self, path):
        self.opened_paths.append(path)
        return self.path_succeeds


class FakeWorkflowSource:
    def current_sha(self, origin):
        return None

    def workflow_names(self, origin, sha):
        return []

    def pinned_bundle(self, origin, sha):
        return None


_TEMP_ROOTS = []


def _tracked_mkdtemp():
    root = tempfile.mkdtemp()
    _TEMP_ROOTS.append(root)
    return root


def _sweep_temp_roots():
    while _TEMP_ROOTS:
        shutil.rmtree(_TEMP_ROOTS.pop(), ignore_errors=True)


class HermeticTuiConfig(Config):
    def __init__(self, autostart_pool=False):
        root = _tracked_mkdtemp()
        home = os.path.join(root, "home")
        os.makedirs(home)
        cfg_path = os.path.join(home, "config")
        seeded = dict(_SEED_KEYS)
        seeded["tui-autostart-pool"] = "true" if autostart_pool else "false"
        seeded["projects"] = os.path.join(root, "projects")
        seeded["specs"] = os.path.join(root, "specs")
        seeded["backups-dir"] = os.path.join(root, "backups-dir")
        os.makedirs(seeded["projects"])
        os.makedirs(seeded["specs"])
        os.makedirs(seeded["backups-dir"])
        with open(cfg_path, "w") as f:
            f.writelines("%s: %s\n" % (k, v) for k, v in seeded.items())
        super().__init__(environ={"LC_HOME": home, "LC_CONFIG": cfg_path})


class NonHermeticContainerError(Exception):
    pass


class FakeSpawner:
    def __init__(self, pid=4242):
        self._pid = pid
        self.pool_spawns = 0

    def spawn_worker(self, role):
        raise NonHermeticContainerError(
            "container.spawner.spawn_worker() was called without a fake in this test container"
        )

    def spawn_pool(self):
        self.pool_spawns += 1
        return self._pid


def _poisoned(port_cls, port_name):
    def _raise(method_name):
        def _fn(self, *a, **kw):
            raise NonHermeticContainerError(
                "container.%s.%s() was called without a fake in this test container"
                % (port_name, method_name)
            )
        return _fn

    attrs = {name: _raise(name) for name in port_cls.__abstractmethods__}
    return type("Poisoned" + port_cls.__name__, (port_cls,), attrs)()


_LIVE_ADAPTER_TYPES = {
    "config": Config,
    "store": SqliteStore,
    "lock": RunLockAdapter,
    "git": GitAdapter,
    "spawner": SpawnerAdapter,
    "workers": WorkersAdapter,
    "fs": FsAdapter,
    "github": GitHubEventsAdapter,
    "breaker": BreakerAdapter,
    "backup": SqliteBackupAdapter,
    "workflow_source": WorkflowSourceAdapter,
    "launcher": LauncherAdapter,
    "workflow_bundle": WorkflowBundleAdapter,
    "worker_log": WorkerLogAdapter,
    "scaffold": ScaffoldAdapter,
}


def assert_hermetic(container):
    for field, real_type in _LIVE_ADAPTER_TYPES.items():
        if type(getattr(container, field)) is real_type:
            raise NonHermeticContainerError(
                "make_test_container built a real %s (%s) - tests would touch "
                "real config, disk, or the network" % (field, real_type.__name__)
            )


def make_test_container(store=None, lock=None, breaker=None, fs=None, workers=None,
                         launcher=None, git=None, spawner=None, github=None, backup=None,
                         workflow_bundle=None, worker_log=None, autostart_pool=False):
    fs_double = fs or FakeFs()
    container = Container(
        store=store or FakeStore(),
        lock=lock or FakeLock(running=False),
        config=HermeticTuiConfig(autostart_pool=autostart_pool),
        workflow_source=FakeWorkflowSource(),
        breaker=breaker or FakeBreakerPort(),
        fs=fs_double,
        workflow_bundle=workflow_bundle if workflow_bundle is not None else fs_double,
        worker_log=worker_log if worker_log is not None else fs_double,
        scaffold=_poisoned(ScaffoldPort, "scaffold"),
        workers=workers or FakeWorkers(),
        launcher=launcher or FakeLauncher(),
        git=git or _poisoned(GitPort, "git"),
        spawner=spawner if spawner is not None else FakeSpawner(),
        github=github or FakeGitHub(),
        backup=backup or _poisoned(BackupPort, "backup"),
    )
    assert_hermetic(container)
    return container


def _start_background_timers_paused(set_interval):
    def _set_interval(self, interval, callback=None, **kwargs):
        if getattr(callback, "__name__", None) in ("_tick_active_glyph", "_refresh"):
            kwargs.setdefault("pause", True)
        return set_interval(self, interval, callback, **kwargs)

    return _set_interval


LightcycleApp.set_interval = _start_background_timers_paused(LightcycleApp.set_interval)
NodeHubScreen.set_interval = _start_background_timers_paused(NodeHubScreen.set_interval)


class TuiSession:
    def __init__(self, container, now=None, upgrade_check=None, size=None):
        self.app = LightcycleApp(container, now=now, upgrade_check=upgrade_check or _no_upgrade_available)
        self.store = container.store
        self._loop = asyncio.new_event_loop()
        self._ctx = contextvars.copy_context()
        self._run_test_cm = self.app.run_test(size=size) if size else self.app.run_test()
        self.pilot = self._run(self._run_test_cm.__aenter__())
        self.pause()

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

    def _glyph_timer_owners(self):
        targets = [self.app, *self.app.screen_stack]
        return [t for t in targets if getattr(t, "_active_glyph_timer", None) is not None]

    def pause(self):
        self._run(self.pilot.pause())
        owners = self._glyph_timer_owners()
        for owner in owners:
            owner._active_glyph_timer.pause()
            owner._active_glyph_frame = ACTIVE_GLYPH_REST_INDEX

    def poll_tick(self):
        self.run(self.app._refresh)
        self.pause()

    def pause_for(self, seconds):
        self._run(self.pilot.pause(seconds))
        self.pause()

    def settle_backlog_filter(self):
        self.pause()
        timer = self.app._backlog_filter_timer
        if timer is not None:
            timer.stop()
            self.app._backlog_filter_timer = None
            self.run(self.app._on_backlog_filter_settled)
        self.pause()

    def settle_done_filter(self):
        self.pause()
        timer = self.app._done_filter_timer
        if timer is not None:
            timer.stop()
            self.app._done_filter_timer = None
            self.run(self.app._on_done_filter_settled)
        self.pause()

    def resize(self, width, height):
        self._run(self.pilot.resize_terminal(width, height))
        self.pause()

    def close(self):
        self._run(self._run_test_cm.__aexit__(None, None, None))
        self._loop.close()


def launch(container, now=None, upgrade_check=None, size=None):
    session = TuiSession(container, now=now, upgrade_check=upgrade_check, size=size)
    session.pause()
    return session


def row_key(session, node_id):
    node = session.store.get_node(node_id)
    return getattr(node, "item", None) or node.id
