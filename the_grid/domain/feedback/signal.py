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

    def matches(self, task) -> bool:
        if task.step != self.step:
            return False
        outcome = task.outcome or ""
        if self.match == "contains":
            return self.outcome in outcome
        return outcome == self.outcome


class Signals:
    def __init__(self, specs):
        self._specs = list(specs)

    @classmethod
    def from_metas(cls, role_metas) -> "Signals":
        specs = []
        for meta in role_metas.values():
            meta = meta or {}
            step = meta.get("step")
            decls = meta.get("signals")
            if not step or not isinstance(decls, dict):
                continue
            for name, decl in decls.items():
                specs.append(SignalSpec.parse(name, step, decl))
        return cls(specs)

    def tally(self, tasks):
        totals = {spec.name: 0 for spec in self._specs}
        for spec in self._specs:
            totals[spec.name] += sum(1 for t in tasks if spec.matches(t))
        return totals
