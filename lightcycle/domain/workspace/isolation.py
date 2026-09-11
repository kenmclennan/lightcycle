import posixpath
from pathlib import PurePosixPath


def has_worktrees_component(path):
    return ".worktrees" in PurePosixPath(path).parts


def refuses_live_store(package_root, live_store_root, target_root):
    if not has_worktrees_component(package_root):
        return False
    return posixpath.normpath(target_root) == posixpath.normpath(live_store_root)
