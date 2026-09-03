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
        self._graph_cache = {}

    def clear_cache(self):
        self._graph_cache = {}

    def _default_pin(self):
        origin = self._config.default_origin()
        sha = self._workflow_source.current_sha(origin)
        if sha is None:
            return None
        names = self._workflow_source.workflow_names(origin, sha)
        return "%s/%s@%s" % (origin, names[0], sha) if len(names) == 1 else None

    def _resolve(self, name):
        if self._workflow_source is None:
            return name, None
        pin = name if name is not None else self._default_pin()
        if pin is None:
            return None, None
        parsed = parse_pin(pin)
        if parsed is None:
            raise ValueError("workflow %r is not a pin '<origin>/<name>@<sha>'" % pin)
        origin, wfname, sha = parsed
        return wfname, self._workflow_source.bundle_path(origin, sha)

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
                "workflow %r must be fully qualified '<origin>/<name>'" % selector)
        origin, _name = parsed
        sha = self._workflow_source.current_sha(origin)
        if sha is None:
            raise ValueError(
                "origin %r has no pulled version; run `lc workflow add`/`upgrade`" % origin)
        return resolve_pin(selector, sha)

    def inherited_selection(self, node):
        return self.workflow_for(node)

    def repin_name(self, current, new_name):
        parsed = parse_pin(current)
        if parsed is None:
            return new_name
        origin, _name, sha = parsed
        return format_pin(origin, new_name, sha)

    def _graph_and_root(self, name):
        wfname, root = self._resolve(name)
        cache_key = (wfname, root)
        if cache_key in self._graph_cache:
            return self._graph_cache[cache_key]
        text = self._fs.workflow_text(wfname, root)
        if text is None:
            if wfname is None:
                result = parse_graph(""), root
            else:
                raise ValueError("workflow %r not found" % name)
        else:
            result = parse_graph(text), root
        self._graph_cache[cache_key] = result
        return result

    def _role_metas_in(self, root):
        return {
            role: (self._fs.parse_step(role, root) or {"meta": {}})["meta"]
            for role in self._fs.step_roles(root)
        }

    def role_metas(self, name=None):
        return self._role_metas_in(self._resolve(name)[1])

    def workflow_meta(self, name=None):
        wfname, root = self._resolve(name)
        return self._fs.workflow_meta(wfname, root)

    def step_skill(self, node):
        stage = node.step if getattr(node, "type", None) == "step" else None
        if not stage:
            return None
        selection = self.inherited_selection(node)
        if selection is None:
            return None
        try:
            graph, root = self._graph_and_root(self.resolve_selection(selection))
        except ValueError:
            return None
        parsed = self._fs.parse_step(graph.file_for(stage), root)
        if not parsed or parsed["meta"].get("model"):
            return None
        return (parsed.get("body") or "").strip() or None

    def _owning_item(self, node):
        item_id = getattr(node, "item", None) or node.id
        try:
            return self._store.get_item(item_id)
        except Exception:
            return None

    def workflow_for(self, step):
        item = self._owning_item(step)
        return item.workflow if item is not None else None

    def workflow_owner(self, node):
        item = self._owning_item(node)
        if item is not None and item.workflow:
            return item.workflow, item.id
        return None, None

    def project_for(self, step):
        item = self._owning_item(step)
        return item.project if item is not None else None

    def load_graph(self, name=None):
        return self._graph_and_root(name)[0]

    def load_flow(self, name=None):
        graph, root = self._graph_and_root(name)
        return Flow.from_graph(graph, self._role_metas_in(root))

    def _pin_for_node(self, node):
        selection = self.workflow_for(node)
        return self.resolve_selection(selection) if selection is not None else None

    def _graph_for_node(self, node):
        try:
            return self.load_graph(self._pin_for_node(node))
        except ValueError:
            return None

    def flow_for(self, node):
        try:
            return self.load_flow(self._pin_for_node(node))
        except ValueError:
            return Flow({})

    def workspace_for_node(self, node):
        graph = self._graph_for_node(node)
        if graph is None:
            return None
        stage = node.step if getattr(node, "type", None) == "step" else None
        return graph.workspace_for(stage) if stage else graph.workspace

    def phase_for(self, node):
        graph = self._graph_for_node(node)
        if graph is None:
            return None
        stage = node.step if getattr(node, "type", None) == "step" else None
        return graph.phase_for(stage) if stage else None

    def phase_for_stage(self, stage, name=None):
        graph, _root = self._graph_and_root(name)
        return graph.phase_for(stage)

    def ends_pass(self, stage, outcome, name=None):
        graph, _root = self._graph_and_root(name)
        return graph.ends_pass(stage, outcome)

    def display_for(self, node):
        graph = self._graph_for_node(node)
        if graph is None:
            return None
        stage = node.step if getattr(node, "type", None) == "step" else None
        return graph.display_for(stage) if stage else None

    def workspace_for_phase(self, node, phase):
        graph = self._graph_for_node(node)
        return graph.workspace_for_phase(phase) if graph is not None else None

    def flow_next(self, step, outcome, name=None):
        return self.load_flow(name).next(step, outcome)

    def meta_for_step(self, step, name=None):
        graph, root = self._graph_and_root(name)
        a = self._fs.parse_step(graph.file_for(step), root)
        return a["meta"] if a else {}

    def file_for_step(self, step, name=None):
        graph, _root = self._graph_and_root(name)
        return graph.file_for(step)

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
