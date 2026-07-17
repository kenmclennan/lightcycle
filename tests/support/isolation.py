import os
import subprocess
from collections.abc import Mapping

import lightcycle.cli as cli
from lightcycle.config import Config
from lightcycle.container import Container


class FrozenEnvironError(Exception):
    pass


class _GuardedEnviron(Mapping):
    def __init__(self, overrides):
        self._overrides = dict(overrides)
        self._baseline = dict(os.environ)

    def __getitem__(self, key):
        if key in self._overrides:
            return self._overrides[key]
        current = os.environ.get(key)
        if current != self._baseline.get(key):
            raise FrozenEnvironError(
                "os.environ[%r] changed after inject_container built this config; "
                "pass extra_env to inject_container instead of mutating os.environ" % key
            )
        raise KeyError(key)

    def __iter__(self):
        return iter(self._overrides)

    def __len__(self):
        return len(self._overrides)


def make_syncable_git_repo(path):
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "t"], check=True)
    subprocess.run(
        ["git", "-C", path, "commit", "-q", "--allow-empty", "-m", "init"], check=True
    )
    subprocess.run(["git", "-C", path, "remote", "add", "origin", path], check=True)


def inject_container(test, *, store, home, config_path, extra_env=None):
    overrides = {"LC_HOME": home, "LC_CONFIG": config_path}
    if extra_env:
        overrides.update(extra_env)
    config = Config(environ=_GuardedEnviron(overrides))
    orig = cli._container
    cli.set_container(Container(store=store, config=config))
    if hasattr(test, "addCleanup"):
        test.addCleanup(lambda: cli.set_container(orig))
    return config
