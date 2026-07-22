import os
import subprocess

from lightcycle.ports.git import GitPort


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)


def git_ok(root, *args):
    return git(root, *args).returncode == 0


def is_git_repo(root):
    return git_ok(root, "rev-parse", "--git-dir")


def is_repo_root(root):
    dotgit = os.path.join(root, ".git")
    return os.path.isdir(dotgit) or os.path.isfile(dotgit)


def remote_url(root):
    proc = git(root, "remote", "get-url", "origin")
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def branch_exists(root, branch):
    return git_ok(root, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch)


def worktree_base(root):
    for ref in ("origin/main", "origin/master"):
        if git_ok(root, "rev-parse", "--verify", "--quiet", "refs/remotes/" + ref):
            return ref
    return None


def sync_to_origin(root):
    if not git_ok(root, "fetch", "origin"):
        return False
    proc = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if proc.returncode != 0:
        return True
    return git_ok(root, "merge", "--ff-only", "@{upstream}")


def clone(url, dest):
    os.makedirs(os.path.dirname(dest.rstrip(os.sep)) or ".", exist_ok=True)
    proc = subprocess.run(["git", "clone", "--quiet", url, dest], capture_output=True, text=True)
    return proc.returncode == 0


def clone_identity(identity, dest):
    os.makedirs(os.path.dirname(dest.rstrip(os.sep)) or ".", exist_ok=True)
    proc = subprocess.run(
        ["gh", "repo", "clone", identity, dest], capture_output=True, text=True
    )
    return proc.returncode == 0


def sync_to_default_branch(root):
    if not git_ok(root, "fetch", "origin"):
        return False
    base = worktree_base(root)
    if base is None:
        return False
    branch = base.split("/", 1)[1]
    current = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not git_ok(root, "checkout", branch) and not git_ok(root, "checkout", "--track", base):
        return False
    if git_ok(root, "merge", "--ff-only", base):
        return True
    if current and current != branch:
        git_ok(root, "checkout", current)
    return False


def remove_worktree(root, path):
    git(root, "worktree", "remove", "--force", path)
    git(root, "worktree", "prune")


def delete_branch(root, branch):
    if branch_exists(root, branch):
        git(root, "branch", "-D", branch)


def delete_remote_branch(root, branch):
    git_ok(root, "push", "origin", "--delete", branch)


def worktree_registered(root, path):
    proc = git(root, "worktree", "list", "--porcelain")
    if proc.returncode != 0:
        return False
    want = os.path.realpath(path)
    for line in proc.stdout.splitlines():
        if line.startswith("worktree ") and os.path.realpath(line[len("worktree ") :]) == want:
            return True
    return False


def has_uncommitted(root):
    return git(root, "status", "--porcelain").stdout.strip() != ""


def commit_all(root, message):
    git(root, "add", "-A")
    return git_ok(root, "commit", "-m", message)


class GitAdapter(GitPort):
    def git(self, root, *args):
        return git(root, *args)

    def git_ok(self, root, *args):
        return git_ok(root, *args)

    def is_git_repo(self, root):
        return is_git_repo(root)

    def is_repo_root(self, root):
        return is_repo_root(root)

    def remote_url(self, root):
        return remote_url(root)

    def branch_exists(self, root, branch):
        return branch_exists(root, branch)

    def worktree_base(self, root):
        return worktree_base(root)

    def sync_to_origin(self, root):
        return sync_to_origin(root)

    def clone(self, url, dest):
        return clone(url, dest)

    def clone_identity(self, identity, dest):
        return clone_identity(identity, dest)

    def sync_to_default_branch(self, root):
        return sync_to_default_branch(root)

    def remove_worktree(self, root, path):
        return remove_worktree(root, path)

    def delete_branch(self, root, branch):
        return delete_branch(root, branch)

    def delete_remote_branch(self, root, branch):
        return delete_remote_branch(root, branch)

    def worktree_registered(self, root, path):
        return worktree_registered(root, path)

    def has_uncommitted(self, root):
        return has_uncommitted(root)

    def commit_all(self, root, message):
        return commit_all(root, message)
