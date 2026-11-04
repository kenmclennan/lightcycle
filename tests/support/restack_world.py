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
    def merge_outcome(self, stage, name=None):
        return self._flow.step_def(stage).pr_merge

    def workspace_for_phase(self, node, phase):
        return None


class WorldWorktrees:
    def target_for_run(self, run):
        return REPO

    def path_for_run(self, run):
        suffix = "-s%d" % run.slice if run.slice > 0 else ""
        return "%s/.worktrees/%s%s" % (REPO, run.item, suffix)


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

    def add_slices(self, name, count=3, bases=None, plain=(), unbased=(), commits=("m1",)):
        item = self.store.create_item(name, "d")
        pid = self.store.open_pass(item)
        bases = bases or {}
        history = list(commits)
        slices = {}
        for n in range(1, count + 1):
            base = bases.get(n, n - 1 if n > 1 else None)
            rid = self.store.open_run(
                item, pid, None, slice=n, slice_name="s%d" % n, base_slice=base)
            branch = "feat/%s-s%d" % (name, n)
            pr = self._new_pr()
            self.store.set_branch(rid, branch)
            self.store.set_pr(rid, pr)
            own = list(history) + ["%s-s%d-c" % (name, n)]
            history = own
            tip = "%s-s%d-tip" % (name, n)
            step = self.store.create_step(
                stage="plain-step" if n in plain else GATE, role="agent", item=item, slice=n)
            entry = {
                "item": item, "branch": branch, "pr": pr, "step": step, "tip": tip,
                "head": tip, "run": rid, "slice": n,
            }
            slices[n] = entry
            self.nodes["%s-s%d" % (name, n)] = entry
            self.remote_tips[branch] = tip
            self.ref_shas[(REPO, "origin/" + branch)] = tip
            self.remote_branches.add((REPO, branch))
            self.remote_commits[branch] = list(own)
            self.history[tip] = list(own)
            self.github._head_shas[pr] = tip
            if base is not None:
                self.github._base_keys[pr] = "acme/widget@" + slices[base]["branch"]
                if n not in unbased:
                    self.store.replace_artifact(
                        item, "stack-base", slices[base]["tip"], label=rid, internal=True)
            self.registered.add("%s/.worktrees/%s-s%d" % (REPO, item, n))
        self.nodes[name] = slices[count]
        return slices

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

    def sync_heads(self):
        for entry in self.nodes.values():
            tip = self.git.remote_tips.get(entry["branch"])
            if tip and entry["pr"] in self.github._head_shas:
                self.github._head_shas[entry["pr"]] = tip

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
