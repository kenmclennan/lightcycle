import os

import pytest

from lightcycle.adapters.gitio import GitAdapter
from lightcycle.config import Config
from lightcycle.container import Container
from lightcycle.ports.backup import BackupPort
from lightcycle.ports.git import GitPort
from lightcycle.ports.spawner import SpawnerPort
from tests.support.fake_fs import FakeFs
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.tui_harness import (
    FakeBreakerPort,
    FakeLauncher,
    FakeLock,
    FakeWorkflowSource,
    HermeticTuiConfig,
    NonHermeticContainerError,
    _poisoned,
    assert_hermetic,
    make_test_container,
)


def _fully_faked_container(**overrides):
    kwargs = dict(
        store=FakeStore(),
        lock=FakeLock(),
        config=HermeticTuiConfig(),
        workflow_source=FakeWorkflowSource(),
        breaker=FakeBreakerPort(),
        fs=FakeFs(),
        workers=FakeWorkers(),
        launcher=FakeLauncher(),
        git=_poisoned(GitPort, "git"),
        spawner=_poisoned(SpawnerPort, "spawner"),
        github=FakeGitHub(),
        backup=_poisoned(BackupPort, "backup"),
    )
    kwargs.update(overrides)
    return Container(**kwargs)


def test_assert_hermetic_accepts_make_test_container_default_output():
    assert_hermetic(make_test_container())


def test_assert_hermetic_rejects_a_real_adapter_and_names_it():
    container = _fully_faked_container(git=GitAdapter())

    with pytest.raises(NonHermeticContainerError, match="git"):
        assert_hermetic(container)


def test_assert_hermetic_rejects_an_unisolated_config():
    container = _fully_faked_container(config=Config(environ={}))

    with pytest.raises(NonHermeticContainerError, match="config"):
        assert_hermetic(container)


@pytest.mark.parametrize("port_name,method_name,args", [
    ("git", "remote_url", ("root",)),
    ("spawner", "spawn_worker", ("role",)),
    ("backup", "list_snapshots", ()),
])
def test_poisoned_stub_raises_naming_port_and_method_on_first_use(port_name, method_name, args):
    container = make_test_container()

    with pytest.raises(NonHermeticContainerError, match="%s.*%s" % (port_name, method_name)):
        getattr(getattr(container, port_name), method_name)(*args)


def test_hermetic_tui_config_answers_seed_keys_beyond_default_origin():
    config = HermeticTuiConfig()

    assert config.default_origin() == "lightcycle"
    assert config.max_agents() == 5
    assert config.backups_dir()
    assert os.path.realpath(config.data_root()) != os.path.realpath(
        os.path.join(os.path.expanduser("~"), ".lightcycle")
    )
