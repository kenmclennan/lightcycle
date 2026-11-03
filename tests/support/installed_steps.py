from lightcycle.ports.workflow_bundle import StepPrompt
from tests.unit.test_doctor import FakeWorkflowBundle, FakeWorkflowSource

AGENT = {"model": "sonnet"}
SCRIPT = {"script": "x.sh"}
HUMAN = {}


def graph(*edges, entry=None):
    lines = ["entry: %s" % (entry or edges[0][0]), "", "edges:"]
    for frm, outcome, to in edges:
        lines.append("  %s %s %s" % (frm, outcome, to))
    return "\n".join(lines) + "\n"


class StepsBundle(FakeWorkflowBundle):
    def __init__(self):
        super().__init__()
        self.metas = {}
        self.names = {}

    def step_roles(self, root):
        return sorted(self.metas.get(root, {}))

    def parse_step(self, role, root):
        if isinstance(root, list):
            root = root[0]
        meta = self.metas.get(root, {}).get(role)
        return None if meta is None else StepPrompt(meta=meta, body="")

    def workflow_names(self, root):
        return sorted(self.names.get(root, {}))

    def workflow_text(self, name, root):
        return self.names.get(root, {}).get(name)


def installed(origins):
    source, bundle = FakeWorkflowSource(), StepsBundle()
    for origin, (current, metas, workflows) in origins.items():
        source.register_origin(origin, current=current)
        if current:
            source.add_bundle(origin, current, 1, current=True)
            root = (origin, current)
            bundle.metas[root] = metas
            bundle.names[root] = workflows
    return source, bundle
