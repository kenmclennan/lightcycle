import os


def _is_under(path, directory):
    path = os.path.normpath(path)
    directory = os.path.normpath(directory)
    return path == directory or path.startswith(directory + os.sep)


def refuses_live_store(package_root, worktrees_dir, target_root):
    if not _is_under(package_root, worktrees_dir):
        return False
    default_root = os.path.dirname(os.path.normpath(worktrees_dir))
    return os.path.normpath(target_root) == default_root
