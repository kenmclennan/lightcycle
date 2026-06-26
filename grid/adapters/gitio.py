"""Git IO: the only caller of git. Repo checks and per-story worktree plumbing."""
import os
import subprocess


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


def worktree_registered(root, path):
    proc = git(root, "worktree", "list", "--porcelain")
    if proc.returncode != 0:
        return False
    want = os.path.realpath(path)
    for line in proc.stdout.splitlines():
        if line.startswith("worktree ") and os.path.realpath(line[len("worktree "):]) == want:
            return True
    return False
