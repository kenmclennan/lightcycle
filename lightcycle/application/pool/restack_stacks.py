from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.pool.pr_lookups import false_on_failure
from lightcycle.application.services.worktree import STACK_BASE, STACK_BRANCH_RETAINED_LABEL
from lightcycle.application.work.stack_runs import STACK_RETARGETED, StackRuns
from lightcycle.domain.runs import RunState
from lightcycle.domain.work import State, node_id_key
from lightcycle.ports.git import (
    RESTACK_CONFLICT,
    RESTACK_PUSHED,
    GitReadError,
    RestackStep,
)
from lightcycle.ports.github import ReadFailure

PARK_PREFIX = "restack of "


@dataclass
class _Node:
    item: str
    run: object
    parent_branch: str
    direct: bool
    kind: str = "item"
    old_base: Optional[str] = None
    lease: Optional[str] = None
    parent_node: Optional["_Node"] = None


@dataclass(frozen=True)
class RestackStacksResponse:
    restacked: List[str] = field(default_factory=list)
    retargeted: List[str] = field(default_factory=list)
    deferred: List[str] = field(default_factory=list)
    escalated: List[str] = field(default_factory=list)
    parked: List[str] = field(default_factory=list)
    swept: List[str] = field(default_factory=list)


class RestackStacksUseCase:
    def __init__(self, store, git, github, worktrees, flow, complete, mark_stale):
        self._store = store
        self._git = git
        self._github = github
        self._worktrees = worktrees
        self._flow = flow
        self._complete = complete
        self._mark_stale = mark_stale
        self._stack_runs = StackRuns(store, flow)
        self._last_notes = {}

    def execute(self) -> RestackStacksResponse:
        out = RestackStacksResponse()
        self._sweep_retained(out)
        children, parents = self._graph()
        for parent in parents:
            if self._process(parent, children.get(parent.id, []), children, out):
                break
        return out

    def _graph(self):
        children = {}
        parents = {}
        for item in self._store.all_items():
            for run in self._stack_runs.node_runs(item.id):
                parent, kind = self._stack_runs.parent_of(run, item.stacks_on)
                if parent is None:
                    continue
                parents[parent.id] = parent
                children.setdefault(parent.id, []).append(_Node(
                    item=item.id, run=run, parent_branch=parent.branch, direct=True, kind=kind))
        for nodes in children.values():
            nodes.sort(key=_order)
        for item in self._store.all_items():
            if item.stacks_on:
                run = self._stack_runs.run_of(item.stacks_on)
                if run is not None:
                    parents[run.id] = run
        return children, sorted(parents.values(), key=lambda r: (node_id_key(r.item), r.slice))

    def _stacked_items(self, parent):
        return [c for c in self._store.items_stacked_on(parent) if c.state != State.DONE]

    def _sweep_retained(self, out):
        for item in self._store.items_with_label(STACK_BRANCH_RETAINED_LABEL):
            runs = [
                r for r in self._store.runs_of(item.id)
                if r.branch and (r.state != RunState.OPEN or item.state == State.DONE)
            ]
            held = False
            for run in runs:
                target = self._worktrees.target_for_run(run)
                try:
                    if not self._git.remote_branch_exists(target, run.branch):
                        continue
                except GitReadError:
                    held = True
                    continue
                if self._stack_runs.has_dependents(run):
                    held = True
                    continue
                outcome = self._git.delete_remote_branch(target, run.branch)
                if outcome is not None and not outcome.ok:
                    held = True
            if held:
                continue
            self._store.label_remove(item.id, STACK_BRANCH_RETAINED_LABEL)
            out.swept.append(item.id)

    def _artifact(self, item, atype, label=None):
        found = None
        for artifact in self._store.item_artifacts(item):
            if artifact.type == atype and artifact.label == label:
                found = artifact.value
        return found

    @staticmethod
    def _label(node):
        return node.run.id if node.run.slice > 0 else None

    def _node_steps(self, node):
        return [
            s for s in self._store.children(node.item)
            if s.type == "step" and s.state != State.DONE and s.slice == node.run.slice
        ]

    def _node_step(self, node):
        steps = self._node_steps(node)
        return steps[0] if steps else None

    def _write_base(self, node, sha):
        self._store.replace_artifact(
            node.item, STACK_BASE, sha, label=self._label(node), internal=True)

    def _note_once(self, node, text):
        step = self._node_step(node)
        if step is None or self._last_notes.get(step.id) == text:
            return
        self._last_notes[step.id] = text
        self._store.note_condition(step.id, text)

    def _recorded_base(self, node, target, merged, parent_pr):
        recorded = self._artifact(node.item, STACK_BASE, self._label(node))
        if recorded:
            return recorded
        branch_ref = "origin/" + node.run.branch
        if node.direct and merged:
            parent_head = self._merged_head(parent_pr)
            if not parent_head:
                return None
            return self._git.merge_base(target, branch_ref, parent_head)
        return self._git.merge_base(target, branch_ref, "origin/" + node.parent_branch)

    def _descendants(self, node, children, out_nodes):
        for child in children.get(node.run.id, []):
            sub = _Node(
                item=child.item, run=child.run, parent_branch=node.run.branch, direct=False,
                kind=child.kind, parent_node=node)
            out_nodes.append(sub)
            self._descendants(sub, children, out_nodes)

    def _owed_retarget(self, node):
        if node.kind == "item":
            return True
        return (
            self._artifact(node.item, STACK_BASE, self._label(node)) is not None
            and not self._stack_runs.retargeted(node.run)
        )

    def _process(self, run, kids, children, out):
        if not run.pr:
            return False
        stacked = self._stacked_items(run.item) if self._is_stack_run(run) else []
        runless = [c for c in stacked if not self._stack_runs.node_runs(c.id)]
        if not kids and not runless:
            return False
        merged = false_on_failure(self._github.is_merged(run.pr))
        head = None
        if not merged:
            head = self._github.head_sha(run.pr)
            if isinstance(head, ReadFailure) or not head:
                return False
        if merged:
            for child in runless:
                self._store.set_stacks_on(child.id, None)
                out.retargeted.append(child.id)
        target = self._worktrees.target_for_run(run)
        fetched = False
        nodes = []
        for kid in kids:
            node = _Node(
                item=kid.item, run=kid.run, parent_branch=run.branch, direct=True, kind=kid.kind)
            if merged and not self._owed_retarget(node):
                continue
            if not fetched:
                fetched = True
                if not self._git.fetch_origin(target).ok:
                    return False
            node.old_base = self._recorded_base(node, target, merged, run.pr)
            if not merged and node.old_base == head:
                continue
            nodes.append(node)
            self._descendants(node, children, nodes)
        if not nodes:
            return False
        for node in nodes:
            if node.old_base is None and not node.direct:
                node.old_base = self._recorded_base(node, target, False, run.pr)
        nodes = self._settled(nodes, target, out)
        if not nodes:
            return False
        return self._apply(nodes, run, target, merged, head, out)

    def _is_stack_run(self, run):
        stack_run = self._stack_runs.run_of(run.item)
        return stack_run is not None and stack_run.id == run.id

    def _settled(self, nodes, target, out):
        excluded = set()
        plan = []
        noted = False
        for node in nodes:
            if node.parent_node is not None and node.parent_node.run.id in excluded:
                excluded.add(node.run.id)
                continue
            text = self._unsettled(node, target)
            if text is None:
                plan.append(node)
                continue
            excluded.add(node.run.id)
            if not noted:
                noted = True
                self._note_once(node, "restack of %s deferred: %s" % (node.run.branch, text))
                out.deferred.append(node.item)
        return plan

    def _merged_head(self, pr):
        view = self._github.pr_view(pr)
        if isinstance(view, ReadFailure):
            return None
        return view.head_sha or None

    def _unsettled(self, node, target):
        run = node.run
        if not run.pr:
            return "the PR is not open yet"
        try:
            if not self._git.remote_branch_exists(target, run.branch):
                return "the branch is not on origin"
        except GitReadError as e:
            return "could not read the branch: %s" % e
        if node.old_base is None:
            return "its base could not be determined"
        steps = self._node_steps(node)
        if len(steps) != 1:
            return "the item has %d open steps, not one" % len(steps)
        flow = self._flow.flow_for(steps[0])
        if flow.step_def(steps[0].stage).pr_head_moved is None:
            return "step %s is not at a gate that re-runs on a moved head" % steps[0].id
        path = self._worktrees.path_for_run(run)
        try:
            if self._git.worktree_registered(target, path) and self._git.has_uncommitted(path):
                return "the worktree has uncommitted changes"
        except GitReadError as e:
            return "could not read the worktree: %s" % e
        return None

    def _apply(self, nodes, parent_run, target, merged, head, out):
        onto_ref = None
        default = None
        if merged:
            onto_ref = self._git.worktree_base(target)
            if onto_ref is None:
                return False
            default = onto_ref[len("origin/"):] if onto_ref.startswith("origin/") else onto_ref
        for node in nodes:
            lease = self._git.ref_sha(target, "origin/" + node.run.branch)
            if lease is None:
                self._note_once(
                    node, "restack of %s deferred: the branch is not on origin"
                    % node.run.branch)
                return False
            node.lease = lease
        if merged and not self._retarget_bases(nodes, default, out):
            return False
        steps = []
        for node in nodes:
            onto = (onto_ref if merged else "origin/" + parent_run.branch) if node.direct \
                else node.parent_node.run.branch
            path = self._live_path(node, target)
            steps.append(RestackStep(
                branch=node.run.branch, lease_sha=node.lease, old_base=node.old_base,
                onto=onto, worktree_path=path))
        outcome = self._git.restack(target, steps)
        by_branch = {n.run.branch: n for n in nodes}
        if outcome.kind == RESTACK_PUSHED:
            self._after_push(nodes, outcome, merged, head, target, onto_ref, out)
            return True
        if outcome.kind == RESTACK_CONFLICT:
            self._escalate(by_branch.get(outcome.branch) or nodes[0], outcome, steps, merged, head, out)
            return True
        self._park(by_branch.get(outcome.branch) or nodes[0], outcome, out)
        return True

    def _live_path(self, node, target):
        path = self._worktrees.path_for_run(node.run)
        try:
            return path if self._git.worktree_registered(target, path) else None
        except GitReadError:
            return None

    def _retarget_bases(self, nodes, default, out):
        for node in nodes:
            if not node.direct:
                continue
            view = self._github.pr_view(node.run.pr)
            if isinstance(view, ReadFailure):
                self._note_once(
                    node, "restack of %s deferred: could not read the PR: %s"
                    % (node.run.branch, view.stderr.strip()))
                return False
            if view.base_ref == default:
                continue
            failure = self._github.set_pr_base(node.run.pr, default)
            if isinstance(failure, ReadFailure):
                self._note_once(
                    node, "restack of %s deferred: could not retarget the PR to %s: %s"
                    % (node.run.branch, default, failure.stderr.strip()))
                return False
        return True

    def _new_base(self, node, outcome, merged, head, target, onto_ref):
        if not node.direct:
            return outcome.tips.get(node.parent_node.run.branch) or node.parent_node.lease
        if merged:
            return self._git.ref_sha(target, onto_ref)
        return head

    def _after_push(self, nodes, outcome, merged, head, target, onto_ref, out):
        for node in nodes:
            new_base = self._new_base(node, outcome, merged, head, target, onto_ref)
            if new_base:
                self._write_base(node, new_base)
            if node.direct and merged:
                self._consume_retarget(node)
                out.retargeted.append(node.item)
            else:
                out.restacked.append(node.item)
            self._mark_stale(node.run.pr)
            step = self._node_step(node)
            if step is not None:
                self._clear_park(step)
                self._store.note(
                    step.id, "restacked %s: base %s -> %s, head %s -> %s" % (
                        node.run.branch, _short(node.old_base), _short(new_base),
                        _short(node.lease), _short(outcome.tips.get(node.run.branch))))

    def _consume_retarget(self, node):
        if node.kind == "item":
            self._store.set_stacks_on(node.item, None)
        else:
            self._store.replace_artifact(
                node.item, STACK_RETARGETED, "1", label=node.run.id, internal=True)

    def _clear_park(self, step):
        park = self._store.get_node(step.id).park
        if park.reason and park.reason.startswith(PARK_PREFIX):
            self._store.update_metadata(step.id, {"reason": None, "needs": None, "tried": None})

    def _escalate_outcome(self, step):
        flow = self._flow.flow_for(step)
        sd = flow.step_def(step.stage)
        if sd.pr_conflict is None:
            return None
        return next(
            (c.escalate_outcome for c in sd.caps.values()
             if c.outcome == sd.pr_conflict and c.escalate_outcome),
            None,
        )

    def _escalate(self, node, outcome, steps, merged, head, out):
        step = self._node_step(node)
        step_for = next((s for s in steps if s.branch == node.run.branch), None)
        onto = step_for.onto if step_for else "?"
        text = (
            "restack of %s conflicts in %s; resolve by hand with `git rebase --onto %s %s %s` "
            "then force-push with a lease" % (
                node.run.branch, ", ".join(outcome.files) or "unknown files", onto,
                node.old_base, node.run.branch))
        if node.direct and merged:
            self._consume_retarget(node)
        elif node.direct:
            if head:
                self._write_base(node, head)
        else:
            self._write_base(node, node.parent_node.lease)
        out.escalated.append(node.item)
        if step is None:
            return
        escalate = self._escalate_outcome(step)
        if escalate and self._complete is not None:
            self._complete.execute(CompleteInput(step=step.id, outcome=escalate, note=text))
            return
        ParkStepUseCase(self._store).execute_once(ParkInput(
            step=step.id, observation=PARK_PREFIX + node.run.branch + " conflicts: " + text,
            decision="rebase the branch by hand, then let the stack continue"))

    def _park(self, node, outcome, out):
        step = self._node_step(node)
        out.parked.append(node.item)
        if step is None:
            return
        lease = node.lease
        if outcome.kind == "lease-lost":
            observation = (
                "%s%s not applied: %s moved on origin after it was read (expected %s)"
                % (PARK_PREFIX, node.run.branch, node.run.branch, lease))
        else:
            observation = "%s%s not applied: %s" % (
                PARK_PREFIX, node.run.branch, outcome.detail or "git failed")
        ParkStepUseCase(self._store).execute_once(ParkInput(
            step=step.id, observation=observation,
            decision=(
                "inspect what was pushed to %s, then let the restack retry on the next tick "
                "or rebase it by hand" % node.run.branch)))


def _order(node):
    return (node_id_key(node.item), node.run.slice)


def _short(sha):
    return (sha or "?")[:10]
