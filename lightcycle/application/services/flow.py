from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.pool import ReadyQueue
from lightcycle.domain.workflows.identity import (
    format_pin,
    parse_pin,
    parse_selector,
    resolve_pin,
)


class FlowService:
    def __init__(self, fs, store, config=None, workflow_source=None):
        self._fs = fs
        self._store = store
        self._config = config
        self._workflow_source = workflow_source

    def _default_pin(self):
        origin = self._config.default_origin()
        sha = self._workflow_source.current_sha(origin)
        if sha is None:
            raise ValueError(
                "default-origin %r has no pulled version; run `lc workflow add`/`upgrade`" % origin)
        names = self._workflow_source.workflow_names(origin, sha)
        if len(names) != 1:
            raise ValueError(
                "default-origin %r has %d workflows; a single-workflow origin is required as the "
                "reference (or name the workflow explicitly)" % (origin, len(names)))
        return "%s/%s@%s" % (origin, names[0], sha)

    def _resolve(self, name):
        if self._workflow_source is None:
            return name, None
        pin = name or self._default_pin()
        parsed = parse_pin(pin)
        if parsed is None:
            raise ValueError("workflow %r is not a pin '<origin>/<name>@<sha>'" % pin)
        origin, wfname, sha = parsed
        return wfname, self._workflow_source.bundle_path(origin, sha)

    def default_root(self):
        return self._resolve(None)[1]

    def resolve_selection(self, selector):
        if self._workflow_source is None:
            return selector
        if selector is None:
            raise ValueError(
                "no workflow selected; pass --workflow <origin>/<name> or set one on an ancestor")
        if parse_pin(selector) is not None:
            return selector
        parsed = parse_selector(selector)
        if parsed is None:
            raise ValueError(
                "--workflow %r must be fully qualified '<origin>/<name>'" % selector)
        origin, _name = parsed
        sha = self._workflow_source.current_sha(origin)
        if sha is None:
            raise ValueError(
                "origin %r has no pulled version; run `lc workflow add`/`upgrade`" % origin)
        return resolve_pin(selector, sha)

    def inherited_selection(self, node):
        for n in self._walk(node):
            if n.workflow:
                return n.workflow
        return None

    def repin_name(self, current, new_name):
        parsed = parse_pin(current)
        if parsed is None:
            return new_name
        origin, _name, sha = parsed
        return format_pin(origin, new_name, sha)

    def _graph_and_root(self, name):
        wfname, root = self._resolve(name)
        text = self._fs.workflow_text(wfname, root)
        if text is None:
            raise ValueError("workflow %r not found" % (name or wfname))
        return parse_graph(text), root

    def _role_metas_in(self, root):
        return {
            role: (self._fs.parse_step(role, root) or {"meta": {}})["meta"]
            for role in self._fs.step_roles(root)
        }

    def role_metas(self, name=None):
        return self._role_metas_in(self._resolve(name)[1])

    def _walk(self, step):
        cur, seen = step, set()
        while cur is not None and cur.id not in seen:
            yield cur
            seen.add(cur.id)
            cur = self._store.get_node(cur.parent) if cur.parent else None

    def workflow_for(self, step):
        for node in self._walk(step):
            if node.workflow:
                return node.workflow
        if self._workflow_source is not None:
            return self._default_pin()
        return None

    def project_for(self, step):
        for node in self._walk(step):
            if getattr(node, "project", None):
                return node.project
        return None

    def load_graph(self, name=None):
        return self._graph_and_root(name)[0]

    def load_flow(self, name=None):
        graph, root = self._graph_and_root(name)
        return Flow.from_graph(graph, self._role_metas_in(root))

    def workspace_for_node(self, node):
        graph = self.load_graph(self.workflow_for(node))
        stage = node.step if getattr(node, "type", None) == "step" else None
        return graph.workspace_for(stage) if stage else graph.workspace

    def phase_for(self, node):
        return "spec" if self.workspace_for_node(node) == "specs" else "code"

    def flow_next(self, step, outcome, name=None):
        return self.load_flow(name).next(step, outcome)

    def meta_for_step(self, step, name=None):
        graph, root = self._graph_and_root(name)
        a = self._fs.parse_step(graph.file_for(step), root)
        return a["meta"] if a else {}

    def outcomes_for(self, step, name=None):
        return self.load_flow(name).outcomes_for(step)

    def is_known_step(self, step, name=None):
        return bool(self.load_flow(name).owner_of(step))

    def owner_of(self, step, name=None):
        return self.load_flow(name).owner_of(step)

    def ci_failed_cap_outcome(self, step, name=None):
        return self.load_flow(name).ci_failed_cap_outcome(step)

    def ci_failed_cap_n(self, step, name=None):
        return self.load_flow(name).ci_failed_cap_n(step)

    def ci_failed_cap_target(self, step, name=None):
        return self.load_flow(name).ci_failed_cap_target(step)

    def effective_transition(self, transition, outcome, prior_count, name=None):
        return self.load_flow(name).effective_transition(transition, outcome, prior_count)

    def ready_roles(self):
        return ReadyQueue(self._store.ready_steps()).distinct_roles()
