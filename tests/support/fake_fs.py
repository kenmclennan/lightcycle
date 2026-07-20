import os


def flow_from_metas(metas):
    from lightcycle.domain.flow import Flow
    from lightcycle.domain.flow.graph import parse_graph

    return Flow.from_graph(parse_graph(graph_text_from_metas(metas)), metas)


def signals_from_metas(metas):
    from lightcycle.domain.feedback.signal import Signals
    from lightcycle.domain.flow.graph import parse_graph

    return Signals.from_graph(parse_graph(graph_text_from_metas(metas)))


def graph_text_from_metas(metas, entry=None, requires=None):
    nodes, edges, hooks, signals, phases = [], [], [], [], []
    for role in sorted(metas):
        meta = metas[role] or {}
        step = meta.get("step")
        if not step:
            continue
        if step != role:
            nodes.append("  %s  %s" % (step, role))
        if meta.get("phase"):
            phases.append("  %s  %s" % (step, meta["phase"]))
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
            elif isinstance(val, (list, tuple, set)):
                hooks.append("  %s  %s  %s" % (hook, step, "  ".join(sorted(val))))
            else:
                hooks.append("  %s  %s  %s" % (hook, step, val))
    out = []
    if entry:
        out.append("entry: %s" % entry)
    if requires:
        out.append("requires: %s" % " ".join(sorted(requires)))
    if nodes:
        out.append("nodes:\n" + "\n".join(nodes))
    if edges:
        out.append("edges:\n" + "\n".join(edges))
    if hooks:
        out.append("hooks:\n" + "\n".join(hooks))
    if signals:
        out.append("signals:\n" + "\n".join(signals))
    if phases:
        out.append("phase:\n" + "\n".join(phases))
    return "\n\n".join(out) + "\n"


class FakeFs:
    def __init__(self, metas=None, files=None, dirs=None, workflow=None, workflows=None,
                 bodies=None):
        self._metas = metas or {}
        self._files = files or {}
        self._dirs = dirs or {}
        self._workflow = workflow
        self._workflows = workflows or {}
        self._bodies = bodies or {}

    def workflow_text(self, name, root=None):
        if name in self._workflows:
            return self._workflows[name]
        if isinstance(self._workflow, dict):
            return self._workflow.get(name)
        if self._workflow is not None:
            return self._workflow
        return graph_text_from_metas(self._metas)

    def workflow_meta(self, name, root=None):
        from lightcycle.adapters.frontmatter import split_frontmatter
        text = self.workflow_text(name, root)
        if not text:
            return {}
        meta, _ = split_frontmatter(text)
        return meta

    def workflow_names(self, root=None):
        return sorted(self._workflows)

    def step_roles(self, root=None):
        return sorted(self._metas)

    def parse_step(self, role, root=None):
        if role not in self._metas:
            return None
        return {"meta": self._metas[role] or {}, "body": self._bodies.get(role, ""), "path": role}

    def read_md(self, relpath, root=None):
        return None

    def worktrees_dir(self, root):
        return os.path.join(root, ".worktrees")

    def store_ready(self):
        return True

    def read_bytes(self, path):
        return self._files.get(path)

    def list_dir(self, path):
        return sorted(self._dirs.get(path, []))

    def ensure_logs_dir(self):
        return "/tmp/fake-logs"

    def ensure_worktrees_ignored(self, root):
        pass
