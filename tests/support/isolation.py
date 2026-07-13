import lightcycle.cli as cli
from lightcycle.config import Config
from lightcycle.container import Container


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
