import subprocess

import lightcycle.cli as cli
from lightcycle.config import Config
from lightcycle.container import Container


def make_syncable_git_repo(path):
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "t"], check=True)
    subprocess.run(
        ["git", "-C", path, "commit", "-q", "--allow-empty", "-m", "init"], check=True
    )
    subprocess.run(["git", "-C", path, "remote", "add", "origin", path], check=True)


def inject_container(test, *, store, home, config_path, extra_env=None):
    environ = {"LC_HOME": home, "LC_CONFIG": config_path}
    if extra_env:
        environ.update(extra_env)
    config = Config(environ=environ)
    orig = cli._container
    cli.set_container(Container(store=store, config=config))
    if hasattr(test, "addCleanup"):
        test.addCleanup(lambda: cli.set_container(orig))
    return config
