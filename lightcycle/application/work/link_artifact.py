from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.application.work.resolve_project_ref import resolve_project_ref
from lightcycle.domain.feedback.review_yield import (
    CAUSED_BY,
    FOUND_BY,
    REVIEW_FINDINGS,
    parse_findings,
)
from lightcycle.domain.guidance.guidance import parse_citation
from lightcycle.domain.runs import RUN_FIELDS
from lightcycle.domain.work import State
from lightcycle.domain.workspace.isolation import has_worktrees_component
from lightcycle.ports.store import NodeNotFoundError, ProjectResolutionError


GUIDANCE_CITED = "guidance-cited"


@dataclass(frozen=True)
class LinkArtifactInput:
    item: str
    atype: str
    value: str
    label: Optional[str] = None
    replace: bool = False
    kind: Optional[str] = None
    internal: bool = False
    step: Optional[str] = None


class LinkArtifactUseCase:
    def __init__(self, store, flow=None):
        self._store = store
        self._flow = flow

    def execute(self, input: LinkArtifactInput) -> None:
        if input.value == "":
            raise UseCaseError(
                "empty value for '%s' on '%s' is refused - attach has no way to store or "
                "clear a blank artifact" % (input.atype, input.item)
            )
        if self._store.default_kind_for(input.atype) == "filepath":
            self._validate_spec(input.item, input.value)
        if input.atype in RUN_FIELDS:
            self._route_to_run(input)
            return
        if input.atype == GUIDANCE_CITED:
            self._record_citation(input)
            return
        if input.atype in (CAUSED_BY, FOUND_BY):
            raise UseCaseError(
                "'%s' is set when creating or editing an item: use `lc new item --%s` or "
                "`lc set <item> --%s`" % (input.atype, input.atype, input.atype)
            )
        if input.atype == REVIEW_FINDINGS:
            self._record_findings(input)
            return
        if input.replace:
            self._store.replace_artifact(
                input.item, input.atype, input.value, input.label,
                internal=input.internal, kind=input.kind,
            )
        else:
            self._refuse_if_duplicate(input)
            self._store.add_artifact(
                input.item, input.atype, input.value, input.label,
                internal=input.internal, kind=input.kind,
            )
        if input.atype == "repo":
            self._derive_project_if_unset(input.item, input.value)

    def _record_citation(self, input):
        step_id = input.item
        try:
            node = self._store.get_node(step_id)
        except (KeyError, NodeNotFoundError):
            node = None
        if node is None or node.type != "step":
            raise UseCaseError(
                "'%s' is not a step - guidance-cited attaches to the step that was "
                "delivered the guidance" % step_id
            )
        existing = self._store.item_artifacts(step_id)
        delivered = []
        for a in existing:
            if a.type == "guidance-delivered":
                delivered = [i for i in a.value.split("\n") if i]
        if not delivered:
            raise UseCaseError(
                "step '%s' was delivered no guidance entries, so there is nothing to cite - "
                "do not attach guidance-cited" % step_id
            )
        ids = parse_citation(input.value)
        if not ids:
            raise UseCaseError(
                "guidance-cited on '%s' names no entry id - pass the delivered ids as a "
                "comma-separated list" % step_id
            )
        undelivered = [i for i in ids if i not in delivered]
        if undelivered:
            raise UseCaseError(
                "guidance-cited on '%s' names %s which were not delivered to that step - "
                "delivered: %s; cite only entries from the guidance section in your prompt"
                % (step_id, ", ".join(undelivered), ", ".join(delivered))
            )
        for a in existing:
            if a.type == GUIDANCE_CITED:
                raise UseCaseError(
                    "step '%s' already has a guidance-cited record (%s) - cite once; "
                    "the first record stands"
                    % (step_id, ", ".join(i for i in a.value.split("\n") if i))
                )
        self._store.add_artifact(
            step_id, GUIDANCE_CITED, "\n".join(ids), input.label,
            internal=True, kind=input.kind,
        )

    def _record_findings(self, input):
        step_id = input.item
        try:
            node = self._store.get_node(step_id)
        except (KeyError, NodeNotFoundError):
            node = None
        if node is None or node.type != "step":
            raise UseCaseError(
                "'%s' is not a step - review-findings attaches to the review step" % step_id
            )
        if self._flow is None or self._flow.flow_for(node).step_def(node.stage).review is None:
            raise UseCaseError(
                "step '%s' (%s) is not a review step - its step file declares no review: key"
                % (step_id, node.stage)
            )
        try:
            parse_findings(input.value)
        except ValueError as e:
            raise UseCaseError("%s" % e)
        exists = any(a.type == REVIEW_FINDINGS for a in self._store.item_artifacts(step_id))
        if exists and not input.replace:
            raise UseCaseError(
                "step '%s' already has review-findings - pass --replace to overwrite them"
                % step_id
            )
        write = self._store.replace_artifact if exists else self._store.add_artifact
        write(step_id, REVIEW_FINDINGS, input.value, input.label, internal=True, kind=input.kind)

    def _derive_project_if_unset(self, item, repo):
        try:
            node = self._store.get_item(item)
        except NodeNotFoundError:
            return
        if node.project:
            return
        try:
            derived = resolve_project_ref(self._store, repo)
        except UseCaseError:
            return
        self._store.edit_node(item, project=derived)

    def _refuse_if_duplicate(self, input):
        exists = any(
            a.type == input.atype and a.label == input.label
            for a in self._store.item_artifacts(input.item)
        )
        if exists:
            labeled = " labeled '%s'" % input.label if input.label else ""
            raise UseCaseError(
                "'%s' already has a '%s' artifact%s - pass --replace to overwrite it, "
                "or a different --label to attach another"
                % (input.item, input.atype, labeled)
            )

    def _route_to_run(self, input):
        node = self._store.get_node(input.item)
        if node.type == "step":
            raise UseCaseError(
                "'%s' is a step; '%s' attaches to an item's open phase run - pass the item id"
                % (input.item, input.atype)
            )
        if node.type != "item":
            raise UseCaseError("'%s' is not an item (type=%s)" % (input.item, node.type))
        acting = self._acting_step(input)
        run = self._current_run(input.item, acting)
        if run is None:
            scope = ""
            if acting is not None and self._flow.phase_for(acting) is not None:
                scope = " for phase '%s'" % self._flow.phase_for(acting)
            raise UseCaseError(
                "item '%s' has no open phase run%s to attach '%s' to"
                % (input.item, scope, input.atype)
            )
        if input.atype == "pr":
            self._set_pr(run, input.value)
        elif input.atype == "branch":
            self._store.set_branch(run.id, input.value)
        else:
            self._store.set_comments_handled_through(run.id, input.value)

    def _set_pr(self, run, value):
        if run.pr != value:
            self._store.record_pr_pin(run.id, value, None)
        else:
            self._store.set_pr(run.id, value)

    def _acting_step(self, input):
        if not input.step or self._flow is None:
            return None
        try:
            step = self._store.get_node(input.step)
        except KeyError:
            return None
        if step.type != "step" or step.item != input.item:
            return None
        return step

    def _current_run(self, item, acting=None):
        if acting is not None and self._flow.phase_for(acting) is not None:
            return self._store.current_run(item, self._flow.phase_for(acting))
        open_runs = self._store.open_runs_of(item)
        if not open_runs:
            return None
        if self._flow is None or len(open_runs) == 1:
            return open_runs[-1]
        phase = self._active_phase(item)
        return next((r for r in reversed(open_runs) if r.phase == phase), open_runs[-1])

    def _active_phase(self, item):
        for child in self._store.children(item):
            if getattr(child, "type", None) == "step" and child.state != State.DONE:
                return self._flow.phase_for(child)
        return None

    def _validate_spec(self, item, value):
        if has_worktrees_component(value):
            raise UseCaseError(
                "spec artifact '%s' points into a worktree checkout ('.worktrees' in the path) - "
                "worktrees are disposable; attach the repo-relative path in the specs repo instead"
                % value
            )
        mismatch = self._spec_project_mismatch(item, value)
        if mismatch is not None:
            raise UseCaseError("spec artifact '%s' %s" % (value, mismatch))

    def _spec_project_mismatch(self, item, value):
        leading = value.split("/", 1)[0]
        repo_value = self._store.get_item(item).repo
        if repo_value is None:
            return None
        registry = ProjectRegistry(self._store)
        try:
            repo_project = registry.find(repo_value)
        except ProjectResolutionError:
            return None
        try:
            leading_project = registry.find(leading)
        except ProjectResolutionError:
            return "leading directory '%s' is not a registered project (item's repo project is '%s')" % (
                leading, repo_project.identity,
            )
        if leading_project.identity != repo_project.identity:
            return "leading directory '%s' resolves to project '%s', not the item's repo project '%s'" % (
                leading, leading_project.identity, repo_project.identity,
            )
        return None
