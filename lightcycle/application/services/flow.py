from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.pool import ReadyQueue


class FlowService:
    def __init__(self, fs, store, config=None):
        self._fs = fs
        self._store = store
        self._config = config

    def role_metas(self, project=None):
        return {
            role: (self._fs.parse_step(role, project) or {"meta": {}})["meta"]
            for role in self._fs.step_roles(project)
        }

    def _default_name(self):
        return self._config.default_workflow() if self._config is not None else None

    def _walk(self, step):
        cur, seen = step, set()
        while cur is not None and cur.id not in seen:
            yield cur
            seen.add(cur.id)
            cur = self._store.get_node(cur.parent) if cur.parent else None

    def workflow_for(self, step):
        nodes = list(self._walk(step))
        for node in nodes:
            if node.workflow:
                return node.workflow
        if self._config is not None:
            return self._config.default_workflow_for(getattr(nodes[-1], "project", None))
        return None

    def project_for(self, step):
        for node in self._walk(step):
            if getattr(node, "project", None):
                return node.project
        return None

    def load_graph(self, name=None, project=None):
        name = name or self._default_name()
        text = self._fs.workflow_text(name, project)
        if text is None:
            raise ValueError("workflow %r not found" % name)
        return parse_graph(text)

    def load_flow(self, name=None, project=None):
        return Flow.from_graph(self.load_graph(name, project), self.role_metas(project))

    def phase_for(self, node):
        name = self.workflow_for(node)
        project = self.project_for(node)
        return "spec" if self.load_graph(name, project).workspace == "specs" else "code"

    def flow_next(self, step, outcome, name=None, project=None):
        return self.load_flow(name, project).next(step, outcome)

    def meta_for_step(self, step, name=None, project=None):
        graph = self.load_graph(name, project)
        a = self._fs.parse_step(graph.file_for(step), project)
        return a["meta"] if a else {}

    def outcomes_for(self, step, name=None, project=None):
        return self.load_flow(name, project).outcomes_for(step)

    def is_known_step(self, step, name=None, project=None):
        return bool(self.load_flow(name, project).owner_of(step))

    def owner_of(self, step, name=None, project=None):
        return self.load_flow(name, project).owner_of(step)

    def ci_failed_cap_outcome(self, step, name=None, project=None):
        return self.load_flow(name, project).ci_failed_cap_outcome(step)

    def ci_failed_cap_n(self, step, name=None, project=None):
        return self.load_flow(name, project).ci_failed_cap_n(step)

    def ci_failed_cap_target(self, step, name=None, project=None):
        return self.load_flow(name, project).ci_failed_cap_target(step)

    def effective_transition(self, transition, outcome, prior_count, name=None, project=None):
        return self.load_flow(name, project).effective_transition(transition, outcome, prior_count)

    def ready_roles(self):
        return ReadyQueue(self._store.ready_steps()).distinct_roles()
