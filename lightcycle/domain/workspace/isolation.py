import os


def _has_worktrees_component(path):
    return ".worktrees" in os.path.normpath(path).split(os.sep)


def refuses_live_store(package_root, live_store_root, target_root):
    if not _has_worktrees_component(package_root):
        return False
    return os.path.normpath(target_root) == os.path.normpath(live_store_root)
