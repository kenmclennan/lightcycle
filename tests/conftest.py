import os
import shutil
import tempfile

import pytest

from tests.support import hermetic_env

_LIVE_HOME = os.path.realpath(os.path.join(hermetic_env.REAL_HOME, ".lightcycle"))


_WORKER_ENV = ("LC_WORKER", "LC_SPAWNID", "LC_ROLE")

_made_homes = []


def _remove_made_homes():
    while _made_homes:
        shutil.rmtree(_made_homes.pop(), ignore_errors=True)


def _fresh_test_home():
    hermetic_env.apply()
    _remove_made_homes()
    home = tempfile.mkdtemp(prefix="lc-test-home-")
    _made_homes.append(home)
    if os.path.realpath(home) == _LIVE_HOME:
        raise RuntimeError("test store home resolved to the live store; aborting")
    os.environ["LC_HOME"] = home
    os.environ.pop("LC_CONFIG", None)
    for var in _WORKER_ENV:
        os.environ.pop(var, None)


def pytest_configure(config):
    _fresh_test_home()


def pytest_unconfigure(config):
    _remove_made_homes()
    hermetic_env.cleanup()


@pytest.fixture(autouse=True)
def _isolate_store_home():
    _fresh_test_home()
    hermetic_env.begin_test()
    yield
    hermetic_env.end_test()


@pytest.fixture(autouse=True)
def _cleanup_tui_harness_temp_dirs():
    yield
    from tests.support.tui_harness import _sweep_temp_roots

    _sweep_temp_roots()
