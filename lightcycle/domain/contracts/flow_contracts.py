from lightcycle.domain.contracts.step_contract import StepContract

FILE_PROVIDES = {"spec"}


class FlowContracts:
    def __init__(self, flow, graph, step_metas):
        self._flow = flow
        self._graph = graph
        self._steps = flow.steps()
        self._contract = {
            s: StepContract.from_meta(step_metas.get(graph.file_for(s))) for s in self._steps
        }
        self._provided = set(FILE_PROVIDES) | set(graph.requires)
        self._dups = []

    def _required(self):
        return {s: self._contract[s].required_inputs() for s in self._steps}

    def _produced(self):
        return {s: self._contract[s].required_outputs() for s in self._steps}

    def entries(self):
        req = self._required()
        return [s for s in self._steps if req[s] <= self._provided]

    def _guaranteed(self):
        prod, entries = self._produced(), set(self.entries())
        universe = set().union(self._provided, *prod.values()) if self._steps else set()
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
                    ctxs.append(set(self._provided))
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

    def _source_stages(self):
        g = self._graph
        stages = set(g.edges) | set(g.nodes) | set(g.signals)
        if g.entry:
            stages.add(g.entry)
        for occs in g.hooks.values():
            for occ in occs:
                if occ:
                    stages.add(occ[0])
        return stages

    def unresolved_steps(self):
        return sorted(s for s in self._source_stages() if not self._flow.owner_of(s))

    def phase_gaps(self):
        if not self._graph.phases:
            return []
        return sorted(s for s in self._steps if self._flow.phase_of(s) is None)

    def unknown_phases(self):
        return sorted(s for s in self._graph.phases if not self._flow.owner_of(s))

    def phase_conflicts(self):
        groups = {}
        for stage, phase in self._graph.phases.items():
            if not self._flow.owner_of(stage):
                continue
            groups.setdefault(phase, set()).add(self._flow.workspace_of(stage))
        return {p: sorted(ws) for p, ws in groups.items() if len(ws) > 1}

    def ok(self):
        return (
            not self.missing() and not self._dups
            and not self.phase_gaps() and not self.unknown_phases() and not self.phase_conflicts()
        )

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
            "phase_gaps": self.phase_gaps(),
            "unknown_phases": self.unknown_phases(),
            "phase_conflicts": self.phase_conflicts(),
            "ok": self.ok(),
        }
