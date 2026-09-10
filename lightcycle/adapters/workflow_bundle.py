import os

from lightcycle.adapters import frontmatter
from lightcycle.ports.workflow_bundle import StepPrompt, WorkflowBundlePort


def _roots(roots):
    return roots if isinstance(roots, (list, tuple)) else [roots]


def step_roles(roots):
    names, seen = [], set()
    for root in _roots(roots):
        adir = os.path.join(root, "steps")
        if not os.path.isdir(adir):
            continue
        for f in os.listdir(adir):
            role = f[:-3]
            if f.endswith(".md") and role not in seen:
                seen.add(role)
                names.append(role)
    return sorted(names)


def read_md(roots, relpath):
    for root in _roots(roots):
        path = os.path.join(root, relpath)
        if os.path.exists(path):
            with open(path) as f:
                text = f.read()
            meta, body = frontmatter.split_frontmatter(text)
            return StepPrompt(meta=meta, body=body)
    return None


def parse_step(roots, role):
    return read_md(roots, os.path.join("steps", "%s.md" % role))


def workflow_text(roots, name):
    for root in _roots(roots):
        path = os.path.join(root, "workflows", "%s.md" % name)
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
    return None


def workflow_meta(roots, name):
    text = workflow_text(roots, name)
    if text is None:
        return {}
    meta, _ = frontmatter.split_frontmatter(text)
    return meta


def workflow_names(roots):
    names, seen = [], set()
    for root in _roots(roots):
        adir = os.path.join(root, "workflows")
        if not os.path.isdir(adir):
            continue
        for f in os.listdir(adir):
            name = f[:-3]
            if f.endswith(".md") and name not in seen:
                seen.add(name)
                names.append(name)
    return sorted(names)


class WorkflowBundleAdapter(WorkflowBundlePort):
    def step_roles(self, root):
        return step_roles([root]) if root else []

    def parse_step(self, role, root):
        return parse_step([root], role) if root else None

    def workflow_text(self, name, root):
        return workflow_text([root], name) if root else None

    def workflow_meta(self, name, root):
        return workflow_meta([root], name) if root else {}

    def workflow_names(self, root):
        return workflow_names([root]) if root else []
