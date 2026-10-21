import sys

from lightcycle.container import make_flow_service, worktrees_for

_container = None


def set_container(impl):
    global _container
    _container = impl


def container():
    return _container


def flow():
    return make_flow_service(
        _container.workflow_bundle, _container.store, _container.config, _container.workflow_source)


def worktrees():
    return worktrees_for(_container)


def require_store():
    if _container.fs.store_ready():
        return True
    sys.stderr.write("no lightcycle store here - run `lc init` first.\n")
    return False
