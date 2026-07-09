import os
import subprocess

from lightcycle.ports.git import GitPort


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)


def git_ok(root, *args):
    return git(root, *args).returncode == 0


def is_git_repo(root):
    return git_ok(root, "rev-parse", "--git-dir")


def branch_exists(root, branch):
    return git_ok(root, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch)


def worktree_base(root):
    for ref in ("origin/main", "origin/master"):
        if git_ok(root, "rev-parse", "--verify", "--quiet", "refs/remotes/" + ref):
            return ref
    return None


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

    def branch_exists(self, root, branch):
        return branch_exists(root, branch)

    def worktree_base(self, root):
        return worktree_base(root)

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
