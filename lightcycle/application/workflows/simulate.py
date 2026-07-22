import os
from dataclasses import dataclass, field
from typing import List

from lightcycle.adapters.simulate import ScriptedGitHub
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.claim_step import ClaimInput
from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.monitor_prs import MonitorPrsUseCase
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.domain.contracts import FlowContracts, StepContract
from lightcycle.domain.flow.simulate_plan import build_coverage_plan
from lightcycle.domain.work.item import Item
from lightcycle.domain.work.state import State

_ADVANCING_HOOKS = ("pr_merge", "pr_conflict")


@dataclass(frozen=True)
class SimulateInput:
    workflow: str


@dataclass(frozen=True)
class SimulateResponse:
    ok: bool
    trace: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)


class WorkflowSimulateUseCase:
    def __init__(self, store, flow, worktrees, claim, complete, projects_root, git):
        self._store = store
        self._flow = flow
        self._worktrees = worktrees
        self._claim = claim
        self._complete = complete
        self._projects_root = projects_root
        self._git = git

    def execute(self, input: SimulateInput) -> SimulateResponse:
        pin = self._flow.resolve_selection(input.workflow)
        graph = self._flow.load_graph(pin)
        step_metas = self._flow.role_metas(pin)
        dom_flow = self._flow.load_flow(pin)
        contracts = FlowContracts(dom_flow, graph, step_metas)
        if not contracts.ok():
            return SimulateResponse(
                ok=False,
                violations=[
                    "static composition invalid (run `lc workflow check %s` first): %s"
                    % (input.workflow, contracts.as_dict())
                ],
            )
        plan = build_coverage_plan(graph, dom_flow)
        trace = []
        violations = []
        for index, walk in enumerate(plan.walks):
            item_id = self._seed_item(pin, graph)
            github = ScriptedGitHub()
            monitor = MonitorPrsUseCase(self._store, github, self._worktrees, self._flow,
                                        self._complete)
            violations += self._drive(item_id, pin, graph, walk, github, monitor, trace, index)
        violations += self._check_teardown_invariant()
        return SimulateResponse(ok=not violations, trace=trace, violations=violations)

    def _seed_item(self, pin, graph):
        item_id = self._store.create_item("simulate: %s" % pin, workflow=pin)
        entry_meta = self._flow.meta_for_step(graph.entry, pin)
        needed = set(graph.requires) | StepContract.from_meta(entry_meta).required_inputs()
        repo_name = "repo-%s" % item_id.replace("/", "-")
        repo_path = os.path.join(self._projects_root, repo_name)
        os.makedirs(repo_path, exist_ok=True)
        self._store.add_project("simulate/%s" % repo_name, local_path=repo_path)
        self._store.add_artifact(item_id, "repo", repo_name)
        for req in sorted(needed):
            if req == "repo":
                continue
            self._store.add_artifact(item_id, req, "<simulated>")
        role = self._flow.owner_of(graph.entry, pin)
        self._store.create_step(
            "%s: simulate" % graph.entry, step=graph.entry, role=role, parent=item_id
        )
        return item_id

    def _is_walk_terminal(self, graph, stage):
        if graph.edges.get(stage):
            return False
        for name in _ADVANCING_HOOKS:
            for occ in graph.hook_occurrences(name):
                if occ and occ[0] == stage:
                    return False
        return True

    def _claim_stage(self, pin, stage, walk_index, violations):
        role = self._flow.owner_of(stage, pin)
        if not role:
            violations.append("walk %d: stage '%s' has no owning role" % (walk_index, stage))
            return None
        resp = self._claim.execute(ClaimInput(role=role))
        if resp is None:
            node = None
            for n in self._store.all_nodes():
                if n.type == "step" and n.step == stage and n.state != State.DONE:
                    node = n
                    break
            reason = node.notes if node is not None else "no ready step"
            violations.append(
                "walk %d: could not claim stage '%s' (role=%s): %s"
                % (walk_index, stage, role, reason)
            )
            return None
        return resp.view.step.id

    def _synthesize_produces(self, item_id, pin, stage):
        meta = self._flow.meta_for_step(stage, pin)
        contract = StepContract.from_meta(meta)
        present = {a.type for a in self._store.item_artifacts(item_id)}
        for req in contract.produces:
            if req.type not in present:
                self._store.add_artifact(item_id, req.type, "<simulated>")
                present.add(req.type)

    def _pr_value(self, item_id, graph, stage):
        phase = graph.phase_for(stage)
        artifacts = tuple(self._store.item_artifacts(item_id))
        return Item(item_id, artifacts).artifact_of("pr", label=phase)

    def _item_closed(self, item_id):
        return self._store.get_node(item_id).state == State.DONE

    def _handle_landing(self, item_id, pin, graph, next_step_id, trace, walk_index):
        node = self._store.get_node(next_step_id)
        trace.append("walk %d: -> %s" % (walk_index, node.step))
        if not self._flow.owner_of(node.step, pin):
            self._close_item(item_id, node.step)
            trace.append(
                "walk %d: %s (unowned terminal, item closed)" % (walk_index, node.step)
            )
            return []
        if not self._is_walk_terminal(graph, node.step):
            return []
        return self._complete_terminal(item_id, pin, node, trace, walk_index)

    def _close_item(self, item_id, reason):
        CloseItemUseCase(self._store, self._worktrees).execute(
            CloseItemInput(item=item_id, reason=reason)
        )

    def _complete_terminal(self, item_id, pin, node, trace, walk_index):
        resp = self._claim.execute(ClaimInput(role=node.role))
        if resp is None:
            fresh = self._store.get_node(node.id)
            reason = fresh.notes or "no ready step"
            return [
                "walk %d: could not claim stage '%s' (role=%s): %s"
                % (walk_index, node.step, node.role, reason)
            ]
        self._synthesize_produces(item_id, pin, node.step)
        try:
            self._complete.execute(CompleteInput(step=node.id, outcome="done"))
        except UseCaseError as e:
            return ["walk %d: %s[done] raised: %s" % (walk_index, node.step, e)]
        if not self._item_closed(item_id):
            return [
                "walk %d: terminal stage '%s' completed but the item did not close"
                % (walk_index, node.step)
            ]
        trace.append("walk %d: %s[done] (terminal, item closed)" % (walk_index, node.step))
        return []

    def _advance_edge(self, item_id, pin, graph, step_id, planned, trace, walk_index):
        declared_target = (graph.edges.get(planned.stage) or {}).get(planned.outcome)
        try:
            resp = self._complete.execute(CompleteInput(step=step_id, outcome=planned.outcome))
        except UseCaseError as e:
            return ["walk %d: %s[%s] raised: %s" % (walk_index, planned.stage, planned.outcome, e)]
        trace.append(
            "walk %d: %s[%s]" % (walk_index, planned.stage, planned.outcome)
        )
        if resp.next_step is None:
            if declared_target is not None:
                return [
                    "walk %d: %s[%s] declares target '%s' but produced no next step (dead end)"
                    % (walk_index, planned.stage, planned.outcome, declared_target)
                ]
            if not self._item_closed(item_id):
                return [
                    "walk %d: %s[%s] has no target and the item did not close"
                    % (walk_index, planned.stage, planned.outcome)
                ]
            return []
        return self._handle_landing(item_id, pin, graph, resp.next_step, trace, walk_index)

    def _advance_hook(self, item_id, pin, graph, step_id, planned, github, monitor, trace,
                      walk_index):
        pr = self._pr_value(item_id, graph, planned.stage)
        if pr is None:
            return [
                "walk %d: stage '%s' needs a pr artifact to script %s but none is present"
                % (walk_index, planned.stage, planned.hook)
            ]
        before = {c.id for c in self._store.children(item_id)}
        if planned.hook == "pr_merge":
            github.script_merge(pr)
        else:
            github.script_conflict(pr)
        try:
            monitor.execute()
        except UseCaseError as e:
            return [
                "walk %d: %s[%s hook] raised: %s"
                % (walk_index, planned.stage, planned.hook, e)
            ]
        trace.append("walk %d: %s[%s hook]" % (walk_index, planned.stage, planned.hook))
        if self._item_closed(item_id):
            return []
        step_now = self._store.get_node(step_id)
        if step_now.state != State.DONE:
            return [
                "walk %d: hook %s at stage '%s' did not advance the step"
                % (walk_index, planned.hook, planned.stage)
            ]
        new_children = [c for c in self._store.children(item_id) if c.id not in before]
        if not new_children:
            return [
                "walk %d: hook %s at '%s' completed with no next step and the item did not close"
                % (walk_index, planned.hook, planned.stage)
            ]
        return self._handle_landing(item_id, pin, graph, new_children[0].id, trace, walk_index)

    def _mention_token(self, graph, stage):
        for occ in graph.hook_occurrences("mention_token"):
            if occ and occ[0] == stage and len(occ) > 1:
                return occ[1]
        return None

    def _drive_feedback(self, item_id, pin, graph, planned, monitor, github, trace, walk_index):
        pr = self._pr_value(item_id, graph, planned.stage)
        if pr is None:
            return [
                "walk %d: stage '%s' needs a pr artifact to script pr_feedback but none is present"
                % (walk_index, planned.stage)
            ]
        token = self._mention_token(graph, planned.stage)
        if token is None:
            return [
                "walk %d: stage '%s' declares pr_feedback but no mention_token to trigger it "
                "with (review_bot_allowlist-only feedback is not covered)" % (walk_index, planned.stage)
            ]
        before = {c.id for c in self._store.children(item_id)}
        github.script_feedback(pr, "%s please take a look" % token)
        try:
            monitor.execute()
        except UseCaseError as e:
            return [
                "walk %d: %s pr_feedback raised: %s" % (walk_index, planned.stage, e)
            ]
        new_children = [
            c for c in self._store.children(item_id)
            if c.id not in before and c.step == planned.outcome and c.state != State.DONE
        ]
        if not new_children:
            return [
                "walk %d: pr_feedback at '%s' did not spawn a '%s' step"
                % (walk_index, planned.stage, planned.outcome)
            ]
        feedback_step = new_children[0]
        self._synthesize_produces(item_id, pin, planned.outcome)
        try:
            self._complete.execute(CompleteInput(step=feedback_step.id, outcome="done"))
        except UseCaseError as e:
            return [
                "walk %d: completing rework step '%s' raised: %s"
                % (walk_index, planned.outcome, e)
            ]
        trace.append(
            "walk %d: %s pr_feedback -> %s (resumed)" % (walk_index, planned.stage, planned.outcome)
        )
        return []

    def _drive(self, item_id, pin, graph, walk, github, monitor, trace, walk_index):
        violations = []
        for planned in walk.steps:
            if self._item_closed(item_id):
                break
            if planned.kind == "hook" and planned.hook == "pr_feedback":
                v = self._drive_feedback(item_id, pin, graph, planned, monitor, github, trace,
                                          walk_index)
                violations += v
                if v:
                    break
                continue
            step_id = self._claim_stage(pin, planned.stage, walk_index, violations)
            if step_id is None:
                break
            self._synthesize_produces(item_id, pin, planned.stage)
            if planned.kind == "edge":
                v = self._advance_edge(item_id, pin, graph, step_id, planned, trace, walk_index)
            else:
                v = self._advance_hook(item_id, pin, graph, step_id, planned, github, monitor,
                                       trace, walk_index)
            violations += v
            if v:
                break
        if not self._item_closed(item_id):
            violations.append(
                "walk %d: item %s did not terminate (walk ended without closing)"
                % (walk_index, item_id)
            )
        return violations

    def _check_teardown_invariant(self):
        violations = []
        leaked_worktrees = set(self._git.created_worktrees()) - set(self._git.torn_down_worktrees())
        for root, path in sorted(leaked_worktrees):
            violations.append("teardown: worktree %s under %s was created but never removed" % (path, root))
        leaked_branches = set(self._git.created_branches()) - set(self._git.torn_down_branches())
        for root, branch in sorted(leaked_branches):
            violations.append("teardown: branch %s in %s was created but never deleted" % (branch, root))
        leaked_remote = (
            set(self._git.created_branches()) - set(self._git.torn_down_remote_branches())
        )
        for root, branch in sorted(leaked_remote):
            violations.append(
                "teardown: remote branch %s in %s was created but never deleted" % (branch, root)
            )
        return violations
