import json
from dataclasses import dataclass, field, replace
from typing import List, Optional

from lightcycle.application.feedback.item_signals import ItemSignals
from lightcycle.application.feedback.retro_scope import RetroScope
from lightcycle.domain import feedback as cfeedback
from lightcycle.domain.feedback import layers
from lightcycle.domain.feedback.review_yield import REVIEW_FINDINGS
from lightcycle.domain.work import State, slow_steps


def _layer_order(key):
    return (1, 0) if key == layers.UNLAYERED else (0, int(key))


@dataclass(frozen=True)
class RetroInput:
    subject: Optional[str] = None
    since: Optional[str] = None
    last: Optional[int] = None
    project: Optional[str] = None
    pending: bool = False


@dataclass(frozen=True)
class FeedbackItem:
    step: str
    text: str


@dataclass(frozen=True)
class RetroResponse:
    subject: str
    reflection_count: int
    feedback: List[FeedbackItem]
    item_signals: List[ItemSignals]
    unreadable: List[str] = field(default_factory=list)


class RetroUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def _signals_resolver(self):
        empty = cfeedback.Signals([])

        def resolve(item):
            selection = self._flow.inherited_selection(item)
            if selection is None:
                return empty
            graph = self._flow.graph_for(item)
            return cfeedback.Signals.from_graph(graph) if graph is not None else empty

        return resolve

    def _figures_resolver(self):
        def figures(item, steps):
            pass_ids = {s.pass_id for s in steps}
            runs = [r for r in self._store.runs_of(item.id) if r.pass_id in pass_ids]
            rejections, findings = {}, {}
            for step in steps:
                if step.type != "step" or step.state != State.DONE:
                    continue
                flow = self._flow.flow_for(step)
                if not flow.declared(step.stage):
                    continue
                review = flow.step_def(step.stage).review
                if review is None:
                    continue
                reported = self._findings_of(step)
                for key, n in layers.findings_by_layer(reported).items():
                    findings[key] = findings.get(key, 0) + n
                if step.outcome != review:
                    for key, n in layers.layer_rejections(reported).items():
                        rejections[key] = rejections.get(key, 0) + n
            keys = sorted(set(rejections) | set(findings), key=_layer_order)
            return {
                "prs": layers.prs_of(runs),
                "prs_merged": layers.prs_merged_of(runs),
                "layers": [
                    {"layer": k, "rejections": rejections.get(k, 0), "findings": findings.get(k, 0)}
                    for k in keys
                ],
            }

        return figures

    def _findings_of(self, step):
        for artifact in self._store.item_artifacts(step.id):
            if artifact.type == REVIEW_FINDINGS:
                return json.loads(artifact.value)
        return None

    def execute(self, input: RetroInput) -> RetroResponse:
        signals_for = self._signals_resolver()
        scope = RetroScope.from_input(input)
        rows, all_refs, all_unreadable = scope.items_and_refs(
            self._store, signals_for, self._figures_resolver())
        label = scope.label

        slow_by_item = {}
        for slow in slow_steps(self._store.all_steps_including_done()):
            slow_by_item.setdefault(slow.step.item, []).append(slow)
        rows = [replace(r, slow_steps=slow_by_item.get(r.item.id, [])) for r in rows]

        reflection_count = len(all_refs)
        feedback = [
            FeedbackItem(step=f["step"], text=f["feedback"])
            for f in cfeedback.Retro(all_refs).feedback()
        ]
        return RetroResponse(
            subject=label, reflection_count=reflection_count, feedback=feedback, item_signals=rows,
            unreadable=all_unreadable,
        )
