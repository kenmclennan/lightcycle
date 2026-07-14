from dataclasses import dataclass, field


_SECTIONS = ("nodes", "edges", "hooks", "signals")


@dataclass(frozen=True)
class WorkflowGraph:
    entry: str
    requires: frozenset = field(default_factory=frozenset)
    workspace: str = "project"
    nodes: dict = field(default_factory=dict)
    edges: dict = field(default_factory=dict)
    hooks: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    workspaces: dict = field(default_factory=dict)

    def file_for(self, stage):
        return self.nodes.get(stage, stage)

    def workspace_for(self, stage):
        return self.workspaces.get(stage, self.workspace)

    def target(self, stage, outcome):
        return (self.edges.get(stage) or {}).get(outcome)

    def hook_occurrences(self, name):
        return self.hooks.get(name, [])


def parse_graph(text):
    entry = None
    requires = frozenset()
    workspace = "project"
    nodes, edges, hooks, signals, workspaces = {}, {}, {}, {}, {}
    section = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] not in " \t":
            head = line.split(":", 1)[0].strip()
            value = line.split(":", 1)[1].strip() if ":" in line else ""
            if head == "entry":
                entry = value
            elif head == "requires":
                requires = frozenset(value.split())
            elif head == "workspace" and value:
                workspace = value
            elif head == "workspace":
                section = "workspace"
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
            frm, outcome = parts[0], parts[1]
            target = parts[2] if len(parts) > 2 else None
            edges.setdefault(frm, {})[outcome] = target
        elif section == "hooks":
            hooks.setdefault(parts[0], []).append(parts[1:])
        elif section == "signals":
            stage, name, decl = parts
            signals.setdefault(stage, {})[name] = decl
        elif section == "workspace":
            stage, ws = parts
            workspaces[stage] = ws
    return WorkflowGraph(
        entry=entry, requires=requires, workspace=workspace,
        nodes=nodes, edges=edges, hooks=hooks, signals=signals, workspaces=workspaces
    )
