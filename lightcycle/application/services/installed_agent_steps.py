from lightcycle.application.services.engine_fragments import with_engine_fragments
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.ports.workflow_bundle import StepPrompt


class InstalledAgentSteps:
    def __init__(self, workflow_source, workflow_bundle, config):
        self._source = workflow_source
        self._bundle = workflow_bundle
        self._config = config

    def _metas(self, root):
        include_roots = with_engine_fragments(root, self._config)
        metas = {}
        for role in self._bundle.step_roles(root):
            try:
                parsed = self._bundle.parse_step(role, include_roots)
            except ValueError:
                parsed = None
            metas[role] = (parsed or StepPrompt(meta={}, body="")).meta
        return metas

    def list(self):
        found = set()
        for origin in self._source.list_origins():
            registry = self._source.read_registry(origin)
            current = getattr(registry, "current", None)
            if not current:
                continue
            root = self._source.pinned_bundle(origin, current)
            metas = self._metas(root)
            for name in self._bundle.workflow_names(root):
                text = self._bundle.workflow_text(name, root)
                if text is None:
                    continue
                try:
                    flow = Flow.from_graph(parse_graph(text), metas)
                except ValueError:
                    continue
                for stage in flow.steps():
                    if flow.step_def(stage).owner == "agent":
                        found.add((origin, stage))
        return sorted(found)
