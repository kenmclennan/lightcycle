from dataclasses import dataclass


@dataclass(frozen=True)
class SignalSpec:
    name: str
    step: str
    outcome: str
    match: str = "exact"

    @classmethod
    def parse(cls, name, step, decl) -> "SignalSpec":
        decl = str(decl)
        if decl.startswith("~"):
            return cls(name=name, step=step, outcome=decl[1:], match="contains")
        return cls(name=name, step=step, outcome=decl)

    def matches(self, step) -> bool:
        if step.step != self.step:
            return False
        outcome = step.outcome or ""
        if self.match == "contains":
            return self.outcome in outcome
        return outcome == self.outcome


UNLABELED_MODEL = "unlabeled"


class Signals:
    def __init__(self, specs):
        self._specs = list(specs)

    @classmethod
    def from_graph(cls, graph) -> "Signals":
        specs = []
        for step, decls in graph.signals.items():
            for name, decl in decls.items():
                specs.append(SignalSpec.parse(name, step, decl))
        return cls(specs)

    def tally(self, steps):
        totals = {spec.name: {} for spec in self._specs}
        for spec in self._specs:
            by_model = totals[spec.name]
            for t in steps:
                if not spec.matches(t):
                    continue
                model = t.model or UNLABELED_MODEL
                by_model[model] = by_model.get(model, 0) + 1
        return totals
