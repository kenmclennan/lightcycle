from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.pr_lookups import flow_for, run_of, skip_unpinned
from lightcycle.application.pool.stack_reads import read_stack
from lightcycle.application.work.gate_hold import GateHold, route_name
from lightcycle.domain.pool import stack_shape
from lightcycle.domain.work import State
from lightcycle.ports.github import PrSync


@dataclass(frozen=True)
class DetectStackShapeResponse:
    shape_changed: List[str] = field(default_factory=list)


class DetectStackShapeUseCase:
    def __init__(self, store, github, flow_service, complete):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._complete = complete
        self._gate_hold = GateHold(store)

    def _observed_bases(self, layers):
        bases = {}
        for layer in layers:
            if layer.state != "open":
                continue
            sync = self._github.pr_sync_state(layer.url)
            if isinstance(sync, PrSync):
                base = sync.base_key.partition("@")[2]
                if base:
                    bases[layer.url] = base
        return bases

    def execute(self) -> DetectStackShapeResponse:
        fired = []
        handled = set()
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE or not step.item:
                continue
            if skip_unpinned(self._store, self._flow_service, step):
                continue
            flow = flow_for(self._flow_service, step)
            sd = flow.step_def(step.stage)
            run = run_of(self._store, self._flow_service, step)
            if run is None or not run.stack:
                continue
            read = read_stack(self._github, run.stack)
            if read.unread:
                continue
            previous = stack_shape.decode(run.stack_seen)
            bases = self._observed_bases(read.layers)
            current = stack_shape.record_of(read.layers, bases, previous)
            held = self._gate_hold.is_held(step.id)
            if previous is None:
                if not held:
                    self._store.set_stack_seen(run.id, stack_shape.encode(current))
                continue
            diff = stack_shape.compare(previous, read.layers, current, read.dissolved)
            encoded = stack_shape.encode(current)
            if not diff.differences:
                if current != previous and not held:
                    self._store.set_stack_seen(run.id, encoded)
                    remaining = sum(1 for l in read.layers if l.state != "merged")
                    for name in diff.newly_merged:
                        if remaining:
                            self._store.note_condition(
                                step.id,
                                "stack progress: %s merged; %d %s remain"
                                % (name, remaining, "layer" if remaining == 1 else "layers"),
                            )
                continue
            if not sd.pr_stack_shape or run.id in handled:
                continue
            if held:
                self._gate_hold.observe(
                    step, "stack shape changed (would route to %s)"
                    % route_name(flow, step, sd.pr_stack_shape))
                continue
            handled.add(run.id)
            with self._store.transaction():
                self._store.set_stack_seen(run.id, encoded)
                self._complete.execute(CompleteInput(
                    step=step.id, outcome=sd.pr_stack_shape,
                    note=stack_shape.describe(diff.differences),
                ))
            fired.append(step.item)
        return DetectStackShapeResponse(shape_changed=fired)
