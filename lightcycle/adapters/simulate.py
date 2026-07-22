from lightcycle.ports.git import GitPort
from lightcycle.ports.github import Comment, GitHubEventsPort
from lightcycle.ports.workers import WorkersPort

_WORKTREE_BASE = "sim-base"


class _GitResult:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


class RecordingGit(GitPort):
    def __init__(self):
        self.calls = []
        self._worktrees = {}
        self._branches = set()

    def _record(self, method, root, *args):
        self.calls.append((root, method, args))

    def created_worktrees(self):
        return [
            (root, args[2]) for root, method, args in self.calls
            if method == "git" and len(args) >= 2 and args[0] == "worktree" and args[1] == "add"
        ]

    def torn_down_worktrees(self):
        return [(root, args[0]) for root, method, args in self.calls if method == "remove_worktree"]

    def created_branches(self):
        out = []
        for root, method, args in self.calls:
            if method != "git" or len(args) < 2 or args[0] != "worktree" or args[1] != "add":
                continue
            if "-b" in args:
                idx = args.index("-b")
                out.append((root, args[idx + 1]))
        return out

    def torn_down_branches(self):
        return [(root, args[0]) for root, method, args in self.calls if method == "delete_branch"]

    def torn_down_remote_branches(self):
        return [
            (root, args[0]) for root, method, args in self.calls
            if method == "delete_remote_branch"
        ]

    def git(self, root, *args):
        self._record("git", root, *args)
        if len(args) >= 2 and args[0] == "worktree" and args[1] == "add":
            path = args[2]
            branch = args[args.index("-b") + 1] if "-b" in args else args[3]
            self._worktrees[(root, path)] = branch
            self._branches.add((root, branch))
        return _GitResult()

    def git_ok(self, root, *args):
        return self.git(root, *args).returncode == 0

    def is_git_repo(self, root):
        self._record("is_git_repo", root)
        return True

    def is_repo_root(self, root):
        self._record("is_repo_root", root)
        return True

    def remote_url(self, root):
        self._record("remote_url", root)
        return None

    def branch_exists(self, root, branch):
        self._record("branch_exists", root, branch)
        return (root, branch) in self._branches

    def worktree_base(self, root):
        self._record("worktree_base", root)
        return _WORKTREE_BASE

    def sync_to_origin(self, root):
        self._record("sync_to_origin", root)
        return True

    def clone(self, url, dest):
        self._record("clone", url, dest)
        return True

    def clone_identity(self, identity, dest):
        self._record("clone_identity", identity, dest)
        return True

    def sync_to_default_branch(self, root):
        self._record("sync_to_default_branch", root)
        return True

    def remove_worktree(self, root, path):
        self._record("remove_worktree", root, path)
        self._worktrees.pop((root, path), None)

    def delete_branch(self, root, branch):
        self._record("delete_branch", root, branch)
        self._branches.discard((root, branch))

    def delete_remote_branch(self, root, branch):
        self._record("delete_remote_branch", root, branch)

    def worktree_registered(self, root, path):
        self._record("worktree_registered", root, path)
        return (root, path) in self._worktrees

    def has_uncommitted(self, root):
        self._record("has_uncommitted", root)
        return False

    def commit_all(self, root, message):
        self._record("commit_all", root, message)


class ScriptedGitHub(GitHubEventsPort):
    def __init__(self):
        self._merged = set()
        self._conflicted = set()
        self._feedback = {}

    def script_merge(self, pr):
        self._merged.add(pr)

    def script_conflict(self, pr):
        self._conflicted.add(pr)

    def script_feedback(self, pr, body, author="reviewer"):
        self._feedback.setdefault(pr, []).append(
            Comment(author=author, body=body, is_top_level=True, created_at=1.0)
        )

    def is_merged(self, pr):
        hit = pr in self._merged
        self._merged.discard(pr)
        return hit

    def is_closed_unmerged(self, pr):
        return False

    def last_push_time(self, pr):
        return 0.0

    def is_conflicted(self, pr):
        hit = pr in self._conflicted
        self._conflicted.discard(pr)
        return hit

    def comments_since(self, pr, since):
        items = self._feedback.pop(pr, [])
        return [c for c in items if c.created_at > since]

    def pull_comments(self, pr, since):
        return []

    def reviews(self, pr, since):
        return []


class NullWorkers(WorkersPort):
    def _refuse(self, name):
        raise AssertionError("not expected during simulation: %s" % name)

    def workers_state(self):
        self._refuse("workers_state")

    def write_workers(self, workers):
        self._refuse("write_workers")

    def pid_alive(self, pid, started=None):
        self._refuse("pid_alive")

    def reap(self):
        self._refuse("reap")

    def kill(self, pid):
        self._refuse("kill")

    def prune_workers(self, keep_dead=None):
        self._refuse("prune_workers")

    def set_step(self, spawnid, step):
        self._refuse("set_step")

    def step_for(self, spawnid):
        self._refuse("step_for")

    def mark_checked(self, spawnid):
        self._refuse("mark_checked")


class SimulateConfig:
    def __init__(self, real_config, specs_root, projects_root):
        self._real = real_config
        self._specs_root = specs_root
        self._projects_root = projects_root

    def __getattr__(self, name):
        return getattr(self._real, name)

    def specs_root(self):
        return self._specs_root

    def projects_root(self):
        return self._projects_root

    def spawn_id(self):
        return None
