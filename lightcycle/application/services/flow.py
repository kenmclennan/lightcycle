from lightcycle.application.flow.engine_steps import engine_display_of
from lightcycle.application.services.engine_fragments import with_engine_fragments
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.pool import ReadyQueue
from lightcycle.domain.workflows.identity import (
    format_pin,
    parse_pin,
    parse_selector,
    resolve_pin,
)
from lightcycle.ports.workflow_bundle import StepPrompt


class FlowService:
    def __init__(self, workflow_bundle, store, config=None, workflow_source=None):
        self._workflow_bundle = workflow_bundle
        self._store = store
        self._config = config
        self._workflow_source = workflow_source
        self._graph_cache = {}
        self._graph_for_cache = {}
        self._flow_for_cache = {}
        self._step_cache = {}
        self._flow_cache = {}

    def clear_cache(self):
        self._graph_cache = {}
        self._graph_for_cache = {}
        self._flow_for_cache = {}
        self._step_cache = {}
        self._flow_cache = {}

    def _parse_step(self, role, roots):
        key = (tuple(roots) if isinstance(roots, (list, tuple)) else roots, role)
        if key not in self._step_cache:
            self._step_cache[key] = self._workflow_bundle.parse_step(role, roots)
        return self._step_cache[key]

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
        return wfname, self._workflow_source.pinned_bundle(origin, sha)

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
        graph, root, _key = self._graph_root_key(name)
        return graph, root

    def _graph_root_key(self, name):
        wfname, root = self._resolve(name)
        cache_key = (wfname, root)
        if cache_key in self._graph_cache:
            graph, root = self._graph_cache[cache_key]
            return graph, root, cache_key
        text = self._workflow_bundle.workflow_text(wfname, root)
        if text is None:
            if wfname is None:
                result = parse_graph(""), root
            else:
                raise ValueError("workflow %r not found" % name)
        else:
            result = parse_graph(text), root
        self._graph_cache[cache_key] = result
        return result[0], result[1], cache_key

    def _with_engine_fragments(self, root):
        return with_engine_fragments(root, self._config)

    def _role_metas_in(self, root):
        include_roots = self._with_engine_fragments(root)
        return {
            role: (self._parse_step(role, include_roots) or StepPrompt(meta={}, body="")).meta
            for role in self._workflow_bundle.step_roles(root)
        }

    def role_metas(self, name=None):
        return self._role_metas_in(self._resolve(name)[1])

    def workflow_meta(self, name=None):
        wfname, root = self._resolve(name)
        return self._workflow_bundle.workflow_meta(wfname, root)

    def step_skill(self, node):
        stage = node.stage if getattr(node, "type", None) == "step" else None
        if not stage:
            return None
        selection = self.inherited_selection(node)
        if selection is None:
            return None
        try:
            graph, root = self._graph_and_root(self.resolve_selection(selection))
        except ValueError:
            return None
        parsed = self._parse_step(graph.file_for(stage), self._with_engine_fragments(root))
        if not parsed or parsed.meta.get("model"):
            return None
        return (parsed.body or "").strip() or None

    def _item_id(self, node):
        return getattr(node, "item", None) or node.id

    def workflow_for(self, step):
        return self._store.item_workflow(self._item_id(step))

    def unpinned_workflow(self, node):
        if self._workflow_source is None:
            return None
        value = self.workflow_for(node)
        return value if value and parse_pin(value) is None else None

    def workflow_owner(self, node):
        item_id = self._item_id(node)
        workflow = self._store.item_workflow(item_id)
        if workflow:
            return workflow, item_id
        return None, None

    def load_graph(self, name=None):
        return self._graph_and_root(name)[0]

    def load_flow(self, name=None):
        graph, root, key = self._graph_root_key(name)
        if key not in self._flow_cache:
            self._flow_cache[key] = Flow.from_graph(graph, self._role_metas_in(root))
        return self._flow_cache[key]

    def graph_for(self, node):
        selection = self.workflow_for(node)
        if selection not in self._graph_for_cache:
            try:
                pin = self.resolve_selection(selection) if selection is not None else None
                self._graph_for_cache[selection] = self.load_graph(pin)
            except ValueError:
                self._graph_for_cache[selection] = None
        return self._graph_for_cache[selection]

    def flow_for(self, node):
        selection = self.workflow_for(node)
        if selection not in self._flow_for_cache:
            try:
                pin = self.resolve_selection(selection) if selection is not None else None
                self._flow_for_cache[selection] = self.load_flow(pin)
            except ValueError:
                self._flow_for_cache[selection] = Flow({})
        return self._flow_for_cache[selection]

    def workspace_for_node(self, node):
        graph = self.graph_for(node)
        if graph is None:
            return None
        stage = node.stage if getattr(node, "type", None) == "step" else None
        return graph.workspace_for(stage) if stage else graph.workspace

    def phase_for(self, node):
        graph = self.graph_for(node)
        if graph is None:
            return None
        stage = node.stage if getattr(node, "type", None) == "step" else None
        return graph.phase_for(stage) if stage else None

    def phase_for_stage(self, stage, name=None):
        graph, _root = self._graph_and_root(name)
        return graph.phase_for(stage)

    def ends_pass(self, stage, outcome, name=None):
        graph, _root = self._graph_and_root(name)
        return graph.ends_pass(stage, outcome)

    def display_for(self, node):
        stage = node.stage if getattr(node, "type", None) == "step" else None
        graph = self.graph_for(node)
        declared = graph.display_for(stage) if (graph is not None and stage) else None
        if declared is not None:
            return declared
        return engine_display_of(stage) if stage else None

    def workspace_for_phase(self, node, phase):
        graph = self.graph_for(node)
        return graph.workspace_for_phase(phase) if graph is not None else None

    def flow_next(self, step, outcome, name=None):
        return self.load_flow(name).next(step, outcome)

    def is_github_heavy(self, step):
        return self.flow_for(step).step_def(step.stage).github_heavy

    def meta_for_step(self, stage, name=None):
        graph, root = self._graph_and_root(name)
        a = self._parse_step(graph.file_for(stage), self._with_engine_fragments(root))
        return a.meta if a else {}

    def meta_for_unpinned_step(self, stage):
        if self._config is None:
            return {}
        a = self._parse_step(stage, self._config.prompts_root())
        return a.meta if a else {}

    def file_for_step(self, stage, name=None):
        graph, _root = self._graph_and_root(name)
        return graph.file_for(stage)

    def outcomes_for(self, stage, name=None):
        return sorted(self.load_flow(name).step_def(stage).routes.keys())

    def routes_for(self, stage, name=None):
        return dict(self.load_flow(name).step_def(stage).routes)

    def step_declared(self, stage, name=None):
        return self.load_flow(name).declared(stage)

    def owner_of(self, stage, name=None):
        return self.load_flow(name).step_def(stage).owner

    def escalated_transition(self, transition, outcome, history, name=None):
        return self.load_flow(name).escalated_transition(
            transition, outcome, history, self._cap_limit,
        )

    def _cap_limit(self, key):
        return getattr(self._config, key.replace("-", "_"))()

    def ready_roles(self):
        return ReadyQueue(self._store.ready_steps()).distinct_roles()
