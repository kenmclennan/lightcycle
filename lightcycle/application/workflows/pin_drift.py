from lightcycle.application.services.engine_fragments import with_engine_fragments
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.flow.remaining_stages import remaining_stages


class PinDrift:
    def __init__(self, workflow_source, workflow_bundle, config):
        self._workflow_source = workflow_source
        self._workflow_bundle = workflow_bundle
        self._config = config

    def changed_step_roles(self, origin, old_sha, new_sha):
        old_root = self._workflow_source.pinned_bundle(origin, old_sha)
        new_root = self._workflow_source.pinned_bundle(origin, new_sha)
        roles = set(self._workflow_bundle.step_roles(old_root)) | set(self._workflow_bundle.step_roles(new_root))
        changed = set()
        old_roots = with_engine_fragments(old_root, self._config)
        new_roots = with_engine_fragments(new_root, self._config)
        for role in roles:
            old_step = self._workflow_bundle.parse_step(role, old_roots)
            new_step = self._workflow_bundle.parse_step(role, new_roots)
            old_body = old_step.body if old_step else None
            new_body = new_step.body if new_step else None
            if old_body != new_body:
                changed.add(role)
        return changed

    def _graph(self, name, root):
        text = self._workflow_bundle.workflow_text(name, root)
        if text is None:
            return None
        try:
            return parse_graph(text)
        except ValueError:
            return None

    @staticmethod
    def _ahead_files(graph, open_steps):
        flow = Flow.from_graph(graph, {})
        stages = remaining_stages(flow, graph.entry, open_steps)
        return {graph.file_for(stage) for stage in stages}

    def new_graph_declares(self, origin, name, new_sha, open_steps):
        graph = self._graph(name, self._workflow_source.pinned_bundle(origin, new_sha))
        if graph is None:
            return False
        flow = Flow.from_graph(graph, {})
        return all(flow.declared(stage) for stage, _running in open_steps)

    def changed_steps_ahead(self, open_steps, origin, name, old_sha, new_sha):
        changed = self.changed_step_roles(origin, old_sha, new_sha)
        old_graph = self._graph(name, self._workflow_source.pinned_bundle(origin, old_sha))
        new_graph = self._graph(name, self._workflow_source.pinned_bundle(origin, new_sha))
        if old_graph is None or new_graph is None:
            return sorted(changed)
        ahead = self._ahead_files(old_graph, open_steps) | self._ahead_files(new_graph, open_steps)
        return sorted(changed & ahead)
