from the_grid.domain.flow import Flow
from the_grid.domain.flow.graph import parse_graph
from the_grid.domain.pool import ReadyQueue


class FlowService:
    def __init__(self, fs, store, config=None):
        self._fs = fs
        self._store = store
        self._config = config

    def role_metas(self):
        return {
            role: (self._fs.parse_step(role) or {"meta": {}})["meta"]
            for role in self._fs.step_roles()
        }

    def _default_name(self):
        return self._config.default_workflow() if self._config is not None else None

    def workflow_for(self, task):
        cur, seen, top = task, set(), task
        while cur is not None and cur.id not in seen:
            if cur.workflow:
                return cur.workflow
            seen.add(cur.id)
            top = cur
            cur = self._store.get_task(cur.parent) if cur.parent else None
        if self._config is not None:
            return self._config.default_workflow_for(getattr(top, "project", None))
        return None

    def load_graph(self, name=None):
        name = name or self._default_name()
        text = self._fs.workflow_text(name)
        if text is None:
            raise ValueError("workflow %r not found" % name)
        return parse_graph(text)

    def load_flow(self, name=None):
        return Flow.from_graph(self.load_graph(name), self.role_metas())

    def flow_next(self, step, outcome, name=None):
        return self.load_flow(name).next(step, outcome)

    def meta_for_step(self, step, name=None):
        role = self.load_flow(name).owner_of(step)
        if not role:
            return {}
        a = self._fs.parse_step(role)
        return a["meta"] if a else {}

    def outcomes_for(self, step, name=None):
        return self.load_flow(name).outcomes_for(step)

    def ready_roles(self):
        return ReadyQueue(self._store.ready_tasks()).distinct_roles()
