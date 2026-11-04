from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.pool.pr_lookups import active_step_any, false_on_failure
from lightcycle.application.services.worktree import STACK_BASE, STACK_BRANCH_RETAINED_LABEL
from lightcycle.application.work.stack_runs import StackRuns
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
        for parent in self._parents():
            if self._process(parent, out):
                break
        return out

    def _parents(self):
        ids = {
            item.stacks_on for item in self._store.all_items()
            if item.stacks_on
        }
        return sorted(ids, key=node_id_key)

    def _children(self, parent):
        return [c for c in self._store.items_stacked_on(parent) if c.state != State.DONE]

    def _sweep_retained(self, out):
        for item in self._store.items_with_label(STACK_BRANCH_RETAINED_LABEL):
            if self._children(item.id):
                continue
            run = self._stack_runs.run_of(item.id)
            if run is None:
                self._store.label_remove(item.id, STACK_BRANCH_RETAINED_LABEL)
                continue
            target = self._worktrees.target_for_run(run)
            outcome = self._git.delete_remote_branch(target, run.branch)
            if outcome is not None and not outcome.ok:
                continue
            self._store.label_remove(item.id, STACK_BRANCH_RETAINED_LABEL)
            out.swept.append(item.id)

    def _artifact(self, item, atype):
        found = None
        for artifact in self._store.item_artifacts(item):
            if artifact.type == atype:
                found = artifact.value
        return found

    def _note_once(self, item, text):
        step = active_step_any(self._store, item)
        if step is None or self._last_notes.get(step.id) == text:
            return
        self._last_notes[step.id] = text
        self._store.note_condition(step.id, text)

    def _recorded_base(self, node, target, merged, parent_pr):
        recorded = self._artifact(node.item, STACK_BASE)
        if recorded:
            return recorded
        branch_ref = "origin/" + node.run.branch
        if node.direct and merged:
            parent_head = self._merged_head(parent_pr)
            if not parent_head:
                return None
            return self._git.merge_base(target, branch_ref, parent_head)
        return self._git.merge_base(target, branch_ref, "origin/" + node.parent_branch)

    def _descendants(self, node, out_nodes):
        for child in self._children(node.item):
            run = self._stack_runs.run_of(child.id)
            if run is None:
                continue
            sub = _Node(
                item=child.id, run=run, parent_branch=node.run.branch, direct=False,
                parent_node=node)
            out_nodes.append(sub)
            self._descendants(sub, out_nodes)

    def _process(self, parent, out):
        run = self._stack_runs.run_of(parent)
        if run is None or not run.pr:
            return False
        children = self._children(parent)
        if not children:
            return False
        merged = false_on_failure(self._github.is_merged(run.pr))
        head = None
        if not merged:
            head = self._github.head_sha(run.pr)
            if isinstance(head, ReadFailure) or not head:
                return False
        target = self._worktrees.target_for_run(run)
        fetched = False
        nodes = []
        for child in children:
            crun = self._stack_runs.run_of(child.id)
            if crun is None:
                if merged:
                    self._store.set_stacks_on(child.id, None)
                    out.retargeted.append(child.id)
                continue
            if not fetched:
                fetched = True
                if not self._git.fetch_origin(target).ok:
                    return False
            node = _Node(item=child.id, run=crun, parent_branch=run.branch, direct=True)
            node.old_base = self._recorded_base(node, target, merged, run.pr)
            if not merged and node.old_base == head:
                continue
            nodes.append(node)
            self._descendants(node, nodes)
        if not nodes:
            return False
        for node in nodes:
            if node.old_base is None and not node.direct:
                node.old_base = self._recorded_base(node, target, False, run.pr)
        reason = self._unsettled(nodes, target)
        if reason is not None:
            node, text = reason
            self._note_once(node.item, "restack of %s deferred: %s" % (node.run.branch, text))
            out.deferred.append(node.item)
            return False
        return self._apply(nodes, run, target, merged, head, out)

    def _merged_head(self, pr):
        view = self._github.pr_view(pr)
        if isinstance(view, ReadFailure):
            return None
        return view.head_sha or None

    def _unsettled(self, nodes, target):
        for node in nodes:
            run = node.run
            if not run.pr:
                return node, "the PR is not open yet"
            try:
                if not self._git.remote_branch_exists(target, run.branch):
                    return node, "the branch is not on origin"
            except GitReadError as e:
                return node, "could not read the branch: %s" % e
            if node.old_base is None:
                return node, "its base could not be determined"
            steps = [
                s for s in self._store.children(node.item)
                if s.type == "step" and s.state != State.DONE
            ]
            if len(steps) != 1:
                return node, "the item has %d open steps, not one" % len(steps)
            flow = self._flow.flow_for(steps[0])
            if flow.step_def(steps[0].stage).pr_head_moved is None:
                return node, "step %s is not at a gate that re-runs on a moved head" % steps[0].id
            path = self._worktrees.path_for_run(run)
            try:
                if self._git.worktree_registered(target, path) and self._git.has_uncommitted(path):
                    return node, "the worktree has uncommitted changes"
            except GitReadError as e:
                return node, "could not read the worktree: %s" % e
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
                    node.item, "restack of %s deferred: the branch is not on origin"
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
                    node.item, "restack of %s deferred: could not read the PR: %s"
                    % (node.run.branch, view.stderr.strip()))
                return False
            if view.base_ref == default:
                continue
            failure = self._github.set_pr_base(node.run.pr, default)
            if isinstance(failure, ReadFailure):
                self._note_once(
                    node.item, "restack of %s deferred: could not retarget the PR to %s: %s"
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
                self._store.replace_artifact(node.item, STACK_BASE, new_base, internal=True)
            if node.direct and merged:
                self._store.set_stacks_on(node.item, None)
                out.retargeted.append(node.item)
            else:
                out.restacked.append(node.item)
            self._mark_stale(node.run.pr)
            step = active_step_any(self._store, node.item)
            if step is not None:
                self._clear_park(step)
                self._store.note(
                    step.id, "restacked %s: base %s -> %s, head %s -> %s" % (
                        node.run.branch, _short(node.old_base), _short(new_base),
                        _short(node.lease), _short(outcome.tips.get(node.run.branch))))

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
        step = active_step_any(self._store, node.item)
        step_for = next((s for s in steps if s.branch == node.run.branch), None)
        onto = step_for.onto if step_for else "?"
        text = (
            "restack of %s conflicts in %s; resolve by hand with `git rebase --onto %s %s %s` "
            "then force-push with a lease" % (
                node.run.branch, ", ".join(outcome.files) or "unknown files", onto,
                node.old_base, node.run.branch))
        if node.direct and merged:
            self._store.set_stacks_on(node.item, None)
        elif node.direct:
            if head:
                self._store.replace_artifact(node.item, STACK_BASE, head, internal=True)
        else:
            self._store.replace_artifact(
                node.item, STACK_BASE, node.parent_node.lease, internal=True)
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
        step = active_step_any(self._store, node.item)
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


def _short(sha):
    return (sha or "?")[:10]
