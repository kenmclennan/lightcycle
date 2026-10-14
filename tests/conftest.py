import os
import tempfile

import pytest

from tests.support import hermetic_env

_LIVE_HOME = os.path.realpath(os.path.join(hermetic_env.REAL_HOME, ".lightcycle"))


_WORKER_ENV = ("LC_WORKER", "LC_SPAWNID", "LC_ROLE")


def _fresh_test_home():
    hermetic_env.apply()
    home = tempfile.mkdtemp(prefix="lc-test-home-")
    if os.path.realpath(home) == _LIVE_HOME:
        raise RuntimeError("test store home resolved to the live store; aborting")
    os.environ["LC_HOME"] = home
    os.environ.pop("LC_CONFIG", None)
    for var in _WORKER_ENV:
        os.environ.pop(var, None)


def pytest_configure(config):
    _fresh_test_home()


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
