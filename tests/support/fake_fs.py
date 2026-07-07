def flow_from_metas(metas):
    from the_grid.domain.flow import Flow
    from the_grid.domain.flow.graph import parse_graph

    return Flow.from_graph(parse_graph(graph_text_from_metas(metas)), metas)


def signals_from_metas(metas):
    from the_grid.domain.feedback.signal import Signals
    from the_grid.domain.flow.graph import parse_graph

    return Signals.from_graph(parse_graph(graph_text_from_metas(metas)))


def graph_text_from_metas(metas, entry=None):
    nodes, edges, hooks, signals = [], [], [], []
    for role in sorted(metas):
        meta = metas[role] or {}
        step = meta.get("step")
        if not step:
            continue
        if step != role:
            nodes.append("  %s  %s" % (step, role))
        for outcome, target in (meta.get("routes") or {}).items():
            edges.append("  %s  %s  %s" % (step, outcome, target))
        for name, decl in (meta.get("signals") or {}).items():
            signals.append("  %s  %s  %s" % (step, name, decl))
        for key, val in meta.items():
            if not key.startswith("on_") or not val:
                continue
            hook = key[3:]
            if val is True:
                hooks.append("  %s  %s" % (hook, step))
            else:
                hooks.append("  %s  %s  %s" % (hook, step, val))
    out = []
    if entry:
        out.append("entry: %s" % entry)
    if nodes:
        out.append("nodes:\n" + "\n".join(nodes))
    if edges:
        out.append("edges:\n" + "\n".join(edges))
    if hooks:
        out.append("hooks:\n" + "\n".join(hooks))
    if signals:
        out.append("signals:\n" + "\n".join(signals))
    return "\n\n".join(out) + "\n"


class FakeFs:
    def __init__(self, metas=None, files=None, dirs=None, workflow=None):
        self._metas = metas or {}
        self._files = files or {}
        self._dirs = dirs or {}
        self._workflow = workflow

    def workflow_text(self, name, project=None):
        if self._workflow is not None:
            return self._workflow
        return graph_text_from_metas(self._metas)

    def step_roles(self, project=None):
        return sorted(self._metas)

    def parse_step(self, role, project=None):
        if role not in self._metas:
            return None
        return {"meta": self._metas[role] or {}, "body": "", "path": role}

    def read_md(self, relpath, project=None):
        return None

    def worktrees_dir(self):
        return "/tmp/fake-worktrees"

    def store_ready(self):
        return True

    def read_bytes(self, path):
        return self._files.get(path)

    def list_dir(self, path):
        return sorted(self._dirs.get(path, []))

    def ensure_logs_dir(self):
        return "/tmp/fake-logs"

    def ensure_override_dirs(self):
        pass

    def ensure_worktrees_ignored(self):
        pass
