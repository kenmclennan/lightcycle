from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.pool.restack_stacks import RestackStacksUseCase
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_git import FakeGit
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_dispatch_pr_feedback import _FlowAdapter, plant_pr

REPO = "/repo"
GATE = "watch-step"
MAIN_SHA = "main-sha"
MAIN_COMMITS = ["m1", "squash"]

_FLOW = flow_from_metas({
    "watcher": {
        "model": "sonnet",
        "step": GATE,
        "routes": {
            "merged": "done-step", "head-moved": "ci-step",
            "conflicted": "fix-step", "gave-up": "conflict-step",
        },
        "on_pr_merge": "merged",
        "on_pr_head_moved": "head-moved",
        "on_pr_conflict": "conflicted",
        "on_pr_conflict_cap": 2,
        "on_pr_conflict_escalate": "gave-up",
    },
    "plain": {"model": "sonnet", "step": "plain-step", "routes": {"done": "done-step"}},
}, disposition={"merged": "completed"})


class WorldFlow(_FlowAdapter):
    def workspace_for_phase(self, node, phase):
        return None


class WorldWorktrees:
    def target_for_run(self, run):
        return REPO

    def path_for_run(self, run):
        return "%s/.worktrees/%s" % (REPO, run.item)


def _pr(n):
    return "https://github.com/acme/widget/pull/%d" % n


class RestackWorld:
    def __init__(self, **git_kwargs):
        self.store = FakeStore()
        self.flow = WorldFlow(_FLOW)
        self.github = FakeGitHub()
        self.stale = []
        self.events = []
        self.git_kwargs = git_kwargs
        self.git = None
        self.nodes = {}
        self.history = {MAIN_SHA: list(MAIN_COMMITS)}
        self.remote_commits = {}
        self.remote_tips = {}
        self.ref_shas = {(REPO, "origin/main"): MAIN_SHA}
        self.remote_branches = set()
        self.registered = set()
        self.dirty = set()
        self.conflicts = {}
        self.merge_bases = {}
        self._pr_count = 0

    def _new_pr(self):
        self._pr_count += 1
        return _pr(self._pr_count)

    def add_node(self, name, parent=None, commits=(), with_pr=True, gate=GATE,
                 stack_base=None, branch_exists=True):
        item = self.store.create_item(name, "d")
        branch = "feat/%s" % name
        pr = self._new_pr() if with_pr else None
        plant_pr(self.store, item, pr, branch=branch)
        if parent is not None:
            self.store.set_stacks_on(item, self.nodes[parent]["item"])
            if pr:
                self.github._base_keys[pr] = "acme/widget@" + self.nodes[parent]["branch"]
        step = self.store.create_step(stage=gate, role="agent", item=item) if gate else None
        tip = "%s-tip" % name
        self.nodes[name] = {
            "item": item, "branch": branch, "pr": pr, "step": step, "tip": tip,
            "head": "%s-head" % name,
        }
        self.remote_tips[branch] = tip
        self.ref_shas[(REPO, "origin/" + branch)] = tip
        if branch_exists:
            self.remote_branches.add((REPO, branch))
        self.remote_commits[branch] = list(commits)
        self.history[tip] = list(commits)
        self.github._head_shas[pr] = self.nodes[name]["head"] if parent is None else tip
        if stack_base is not None:
            self.store.replace_artifact(item, "stack-base", stack_base, internal=True)
        self.registered.add("%s/.worktrees/%s" % (REPO, item))
        return self.nodes[name]

    def sha_for(self, name, commits):
        sha = "%s-sha" % name
        self.history[sha] = list(commits)
        self.ref_shas[(REPO, sha)] = sha
        return sha

    def build(self):
        self.git = FakeGit(
            repos={REPO}, base="origin/main", remote_branches=self.remote_branches,
            ref_shas=self.ref_shas, remote_tips=self.remote_tips,
            restack_conflicts=self.conflicts, merge_bases=self.merge_bases,
            history_of=self.history, remote_commits=self.remote_commits,
            registered=self.registered, dirty=self.dirty,
            on_restack=self._on_restack, **self.git_kwargs)
        return self.git

    def _on_restack(self, steps):
        self.events.append((
            "restack", [s.branch for s in steps], list(self.github.base_edits)))

    def use_case(self):
        if self.git is None:
            self.build()
        complete = CompleteStepUseCase(self.store, self.flow)
        return RestackStacksUseCase(
            self.store, self.git, self.github, WorldWorktrees(), self.flow, complete,
            self.stale.append)

    def merge(self, name):
        self.github._merged.add(self.nodes[name]["pr"])

    def head(self, name):
        return self.github._head_shas[self.nodes[name]["pr"]]

    def set_head(self, name, sha):
        self.github._head_shas[self.nodes[name]["pr"]] = sha

    def item(self, name):
        return self.nodes[name]["item"]

    def step(self, name):
        return self.nodes[name]["step"]

    def own_commits(self, name):
        branch = self.nodes[name]["branch"]
        return [c for c in self.git.remote_commits[branch] if c not in MAIN_COMMITS]
