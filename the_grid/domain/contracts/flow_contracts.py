"""FlowContracts: static analysis of an assembled flow's artifact contracts.

Contracts are read from the file that DECLARES a step (its accepts/produces
frontmatter), not from the owner: a human step's owner is the literal "human", but
its contract still lives in its own file. The analysis answers: which steps can be
filed (entries), which are unreachable, which require an input no path guarantees
(missing), which route targets are human terminals, and which steps are declared
by more than one role (dups).
"""
from the_grid.domain.contracts.step_contract import StepContract

FILE_PROVIDES = {"spec"}


class FlowContracts:

    def __init__(self, flow, role_metas):
        self._flow = flow
        self._role_metas = role_metas
        self._declarer, self._dups = self._declare()
        self._steps = flow.steps()
        self._contract = {s: StepContract.from_meta(role_metas.get(self._declarer.get(s)))
                          for s in self._steps}

    def _declare(self):
        declarer, dups = {}, []
        for role in sorted(self._role_metas):
            step = (self._role_metas[role] or {}).get("step")
            if not step:
                continue
            if step in declarer:
                dups.append("step '%s' owned by both %s and %s" % (step, declarer[step], role))
            else:
                declarer[step] = role
        return declarer, dups

    def _required(self):
        return {s: self._contract[s].required_inputs() for s in self._steps}

    def _produced(self):
        return {s: self._contract[s].required_outputs() for s in self._steps}

    def entries(self):
        req = self._required()
        return [s for s in self._steps if req[s] <= FILE_PROVIDES]

    def _guaranteed(self):
        """Greatest fixpoint: artifact types guaranteed present when each step starts -
        the intersection over its incoming contexts (the entry budget for filable steps,
        plus each predecessor's guaranteed set unioned with what it produces)."""
        prod, entries = self._produced(), set(self.entries())
        universe = set().union(FILE_PROVIDES, *prod.values()) if self._steps else set()
        incoming = {s: [] for s in self._steps}
        for src in self._steps:
            for nxt in self._flow.targets_from(src):
                if nxt in incoming:
                    incoming[nxt].append(src)
        ga = {s: set(universe) for s in self._steps}
        for _ in range(len(self._steps) + 2):
            for s in self._steps:
                ctxs = []
                if s in entries:
                    ctxs.append(set(FILE_PROVIDES))
                for src in incoming[s]:
                    ctxs.append(ga[src] | prod[src])
                ga[s] = set(universe) if not ctxs else set.intersection(*ctxs)
        return ga

    def _reachable(self):
        reach, stack = set(), list(self.entries())
        while stack:
            s = stack.pop()
            if s in reach:
                continue
            reach.add(s)
            stack += [n for n in self._flow.targets_from(s) if self._flow.owner_of(n)]
        return reach

    def unreachable(self):
        reach = self._reachable()
        return [s for s in self._steps if s not in reach]

    def missing(self):
        req, ga, reach = self._required(), self._guaranteed(), self._reachable()
        return {s: sorted(req[s] - ga[s]) for s in self._steps if s in reach and req[s] - ga[s]}

    def terminals(self):
        targets = set()
        for s in self._steps:
            targets.update(self._flow.targets_from(s))
        return sorted(t for t in targets if not self._flow.owner_of(t))

    def duplicates(self):
        return list(self._dups)

    def ok(self):
        return not self.missing() and not self._dups

    def as_dict(self):
        return {
            "steps": self._steps,
            "req": self._required(),
            "opt": {s: self._contract[s].optional_inputs() for s in self._steps},
            "prod": self._produced(),
            "entries": self.entries(),
            "unreachable": self.unreachable(),
            "missing": self.missing(),
            "terminals": self.terminals(),
            "dups": self.duplicates(),
            "ok": self.ok(),
        }
