from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lightcycle.application.feedback.retro_scope import RetroScope
from lightcycle.domain import feedback as cfeedback
from lightcycle.domain.work import Item


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
class ItemSignals:
    item: Item
    signals: Dict[str, Dict[str, int]]
    reflections: int
    durations: Dict[str, Optional[float]] = field(default_factory=dict)

    def total_duration(self) -> Optional[float]:
        known = [v for v in self.durations.values() if v is not None]
        return sum(known) if known else None


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
        cache = {}
        empty = cfeedback.Signals([])

        def resolve(item):
            selection = self._flow.inherited_selection(item)
            if selection is None:
                return empty
            if selection not in cache:
                try:
                    pin = self._flow.resolve_selection(selection)
                    cache[selection] = cfeedback.Signals.from_graph(self._flow.load_graph(pin))
                except ValueError:
                    cache[selection] = empty
            return cache[selection]

        return resolve

    def execute(self, input: RetroInput) -> RetroResponse:
        signals_for = self._signals_resolver()
        scope = RetroScope.from_input(input)
        rows, all_refs, all_unreadable = scope.items_and_refs(self._store, signals_for)
        label = scope.label

        reflection_count = len(all_refs)
        feedback = [
            FeedbackItem(step=f["step"], text=f["feedback"])
            for f in cfeedback.Retro(all_refs).feedback()
        ]
        return RetroResponse(
            subject=label, reflection_count=reflection_count, feedback=feedback, item_signals=rows,
            unreadable=all_unreadable,
        )
