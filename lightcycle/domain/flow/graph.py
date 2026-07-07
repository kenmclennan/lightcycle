from dataclasses import dataclass, field


_SECTIONS = ("nodes", "edges", "hooks", "signals")


@dataclass(frozen=True)
class WorkflowGraph:
    entry: str
    nodes: dict = field(default_factory=dict)
    edges: dict = field(default_factory=dict)
    hooks: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)

    def file_for(self, stage):
        return self.nodes.get(stage, stage)

    def target(self, stage, outcome):
        return (self.edges.get(stage) or {}).get(outcome)

    def hook_stage(self, name):
        toks = self.hooks.get(name)
        return toks[0] if toks else None

    def hook_value(self, name):
        toks = self.hooks.get(name)
        return toks[1] if toks and len(toks) > 1 else None


def parse_graph(text):
    entry = None
    nodes, edges, hooks, signals = {}, {}, {}, {}
    section = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] not in " \t":
            head = line.split(":", 1)[0].strip()
            if head == "entry":
                entry = line.split(":", 1)[1].strip()
            elif head in _SECTIONS and line.rstrip().endswith(":"):
                section = head
            else:
                section = None
            continue
        parts = line.split()
        if section == "nodes":
            stage, step_file = parts
            nodes[stage] = step_file
        elif section == "edges":
            frm, outcome, target = parts
            edges.setdefault(frm, {})[outcome] = target
        elif section == "hooks":
            hooks[parts[0]] = parts[1:]
        elif section == "signals":
            stage, name, decl = parts
            signals.setdefault(stage, {})[name] = decl
    return WorkflowGraph(entry=entry, nodes=nodes, edges=edges, hooks=hooks, signals=signals)
