from the_grid.domain.flow import Flow
from the_grid.domain.flow.graph import parse_graph
from the_grid.domain.pool import ReadyQueue


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

    def _walk(self, task):
        cur, seen = task, set()
        while cur is not None and cur.id not in seen:
            yield cur
            seen.add(cur.id)
            cur = self._store.get_task(cur.parent) if cur.parent else None

    def workflow_for(self, task):
        nodes = list(self._walk(task))
        for node in nodes:
            if node.workflow:
                return node.workflow
        if self._config is not None:
            return self._config.default_workflow_for(getattr(nodes[-1], "project", None))
        return None

    def project_for(self, task):
        for node in self._walk(task):
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

    def flow_next(self, step, outcome, name=None, project=None):
        return self.load_flow(name, project).next(step, outcome)

    def meta_for_step(self, step, name=None, project=None):
        role = self.load_flow(name, project).owner_of(step)
        if not role:
            return {}
        a = self._fs.parse_step(role, project)
        return a["meta"] if a else {}

    def outcomes_for(self, step, name=None, project=None):
        return self.load_flow(name, project).outcomes_for(step)

    def ready_roles(self):
        return ReadyQueue(self._store.ready_tasks()).distinct_roles()
