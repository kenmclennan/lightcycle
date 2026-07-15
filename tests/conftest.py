import os
import tempfile

import pytest

from lightcycle.config import Config

_LIVE_HOME = os.path.realpath(Config(environ={}).default_data_root())


_WORKER_ENV = ("LC_WORKER", "LC_SPAWNID", "LC_ROLE")


def _fresh_test_home():
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
    yield
