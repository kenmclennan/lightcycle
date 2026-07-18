import datetime
import os
import uuid

from lightcycle.ports.store import StorePort
from lightcycle.domain.work import Artifact, Node, NodeView, State, derive_state


def _new_id():
    return "fake-" + uuid.uuid4().hex[:8]


def _label_value(labels, prefix):
    for l in labels:
        if l.startswith(prefix):
            return l[len(prefix):]
    return None


def labels_for(*, role=None, step=None, project=None, goal=None, attention=False):
    parts = []
    if role:
        parts.append("for:%s" % role)
    if step:
        parts.append("step:%s" % step)
    if project:
        parts.append("project:%s" % project)
    if goal:
        parts.append("goal:%s" % goal)
    if attention:
        parts.append("attention")
    return parts


def record_to_node(record):
    labels = record.get("labels") or []
    role = _label_value(labels, "for:")
    meta = record.get("metadata") or {}
    closed = record.get("state") == "done"
    if record.get("type") == "step" or closed:
        resolved_state = derive_state(
            record.get("type"),
            closed,
            record.get("assignee"),
            record.get("dep_count") or 0,
            [],
        )
    else:
        resolved_state = None
    return Node(
        id=record["id"],
        title=record.get("title", ""),
        type=record.get("type"),
        parent=record.get("parent"),
        role=role,
        step=_label_value(labels, "step:"),
        state=resolved_state,
        project=_label_value(labels, "project:"),
        goal=_label_value(labels, "goal:"),
        artifacts=[Artifact.from_dict(a) for a in (meta.get("artifacts") or [])],
        description=record.get("description"),
        needs=meta.get("needs"),
        outcome=record.get("outcome"),
        deps=record.get("dep_count") or 0,
        notes=record.get("notes"),
        claimed_by=record.get("assignee"),
        workflow=record.get("workflow"),
        theme=record.get("parent") if record.get("type") == "item" else meta.get("theme"),
        since=meta.get("since"),
        fired_at=meta.get("fired_at"),
        closed_at=record.get("closed_at"),
        attention="attention" in labels,
        model=meta.get("model"),
    )


class FakeStore(StorePort):
    def __init__(self, now=None):
        self._records = {}
        self._deps = {}
        self._history = {}
        self._now = now or (lambda: datetime.datetime.now().isoformat())

    def _new_record(self, **fields):
        b = {
            "id": _new_id(),
            "title": "",
            "type": "step",
            "labels": [],
            "state": "ready",
            "assignee": None,
            "metadata": {},
            "parent": None,
            "dep_count": 0,
            "outcome": None,
            "notes": None,
            "closed_at": None,
            "description": None,
        }
        b.update(fields)
        return b

    def _get(self, tid):
        try:
            return self._records[tid]
        except KeyError:
            raise KeyError("step not found: %s" % tid)

    def _to_node(self, record):
        node = record_to_node(record)
        if node.state is None:
            child_states = [
                self._to_node(r).state
                for r in self._records.values()
                if r.get("parent") == record["id"]
            ]
            node.state = derive_state(
                node.type, False, node.claimed_by, bool(node.deps), child_states
            )
        return node

    def item_artifacts(self, item_id):
        b = self._get(item_id)
        return [Artifact.from_dict(a) for a in ((b.get("metadata") or {}).get("artifacts") or [])]

    def add_artifact(self, item_id, atype, value, label=None):
        b = self._get(item_id)
        meta = dict(b.get("metadata") or {})
        artifacts = list(meta.get("artifacts") or [])
        entry = {"type": atype, "value": value}
        if label:
            entry["label"] = label
        artifacts.append(entry)
        meta["artifacts"] = artifacts
        b["metadata"] = meta

    def replace_artifact(self, item_id, atype, value, label=None):
        b = self._get(item_id)
        meta = dict(b.get("metadata") or {})
        artifacts = [a for a in (meta.get("artifacts") or []) if a.get("type") != atype]
        entry = {"type": atype, "value": value}
        if label:
            entry["label"] = label
        artifacts.append(entry)
        meta["artifacts"] = artifacts
        b["metadata"] = meta

    def all_nodes(self):
        return [self._to_node(b) for b in self._records.values()
                if b.get("state") != "done"]

    def all_steps(self):
        return [self._to_node(b) for b in self._records.values()
                if b.get("type") == "step" and b.get("state") != "done"]

    def get_node(self, tid):
        return self._to_node(self._get(tid))

    def node_view(self, tid):
        t = self.get_node(tid)
        arts = self.item_artifacts(t.parent) if t.parent else t.artifacts
        return NodeView(step=t, item_artifacts=list(arts))

    def present_types(self, step):
        item = step.parent or step.id
        return {a.type for a in self.item_artifacts(item)}

    def reassign(self, tid, role):
        cur = self.get_node(tid).role
        if cur and cur != role:
            self.label_remove(tid, "for:%s" % cur)
        self.label_add(tid, "for:%s" % role)
        self.update_state(tid, State.READY)
        self.assign(tid, "")

    def route_to_human(self, tid, note):
        self.note(tid, note)
        self.reassign(tid, "human")

    def closed_items(self):
        result = []
        for b in self._records.values():
            if b.get("type") != "item" or b.get("state") != "done":
                continue
            result.append(
                {
                    "id": b["id"],
                    "title": b.get("title", ""),
                    "closed_at": b.get("closed_at"),
                    "outcome": b.get("outcome"),
                    "artifacts": [
                        Artifact.from_dict(a)
                        for a in ((b.get("metadata") or {}).get("artifacts") or [])
                    ],
                }
            )
        return result

    def ensure_store(self):
        pass

    def reclaim(self, tid):
        self.update_state(tid, State.READY)
        self.assign(tid, "")

    def note(self, tid, text):
        b = self._get(tid)
        existing = b.get("notes")
        b["notes"] = (existing + "\n" + text) if existing else text

    def set_notes(self, tid, text):
        self._get(tid)["notes"] = text or None

    def close(self, tid, reason):
        b = self._get(tid)
        if b.get("state") == "done":
            return
        b["state"] = "done"
        b["outcome"] = reason
        b["closed_at"] = datetime.datetime.now().isoformat()
        self._record_history(tid, State.DONE)
        for other_id, blockers in self._deps.items():
            if tid in blockers:
                other = self._records.get(other_id)
                if other and other.get("state") != "done":
                    other["dep_count"] = max(0, (other.get("dep_count") or 0) - 1)

    def complete_step_atomic(self, step, outcome, expected_assignee, next_step_spec):
        expected = expected_assignee or ""
        b = self._get(step)
        if b.get("state") == "done":
            return (False, None)
        assignee = b.get("assignee") or ""
        if expected and assignee and assignee != expected:
            return (False, None)
        self.close(step, outcome)
        new_id = None
        if next_step_spec is not None:
            new_id = self.create_step(**next_step_spec.as_kwargs())
        return (True, new_id)

    def disconnect(self):
        pass

    def update_metadata(self, tid, meta):
        self._get(tid)["metadata"] = dict(meta)

    def set_model(self, tid, model):
        b = self._get(tid)
        meta = dict(b.get("metadata") or {})
        meta["model"] = model
        b["metadata"] = meta

    def label_add(self, tid, label):
        b = self._get(tid)
        if label not in b["labels"]:
            b["labels"].append(label)

    def label_remove(self, tid, label):
        b = self._get(tid)
        b["labels"] = [l for l in b["labels"] if l != label]

    def update_state(self, tid, state):
        self._get(tid)["state"] = str(state)
        self._record_history(tid, state)

    def _record_history(self, tid, state):
        self._history.setdefault(tid, []).append((str(state), self._now()))

    def assign(self, tid, assignee):
        self._get(tid)["assignee"] = assignee or None

    def dep_add(self, node_id, blocked_by):
        if node_id not in self._deps:
            self._deps[node_id] = set()
        self._deps[node_id].add(blocked_by)
        blocker = self._records.get(blocked_by)
        if blocker and blocker.get("state") != "done":
            b = self._get(node_id)
            b["dep_count"] = (b.get("dep_count") or 0) + 1

    def dep_remove(self, node_id, blocked_by):
        deps = self._deps.get(node_id)
        if not deps or blocked_by not in deps:
            return False
        deps.discard(blocked_by)
        blocker = self._records.get(blocked_by)
        if blocker and blocker.get("state") != "done":
            b = self._get(node_id)
            b["dep_count"] = max(0, (b.get("dep_count") or 0) - 1)
        return True

    def _ready_records(self):
        return [
            b
            for b in self._records.values()
            if b.get("state") == "ready"
            and not b.get("assignee")
            and not (b.get("dep_count") or 0)
            and b.get("type") == "step"
        ]

    def ready_steps(self):
        return [self._to_node(b) for b in self._ready_records()]

    def claim_ready(self, role):
        candidates = [
            b for b in self._ready_records() if "for:%s" % role in (b.get("labels") or [])
        ]
        if not candidates:
            return None
        b = candidates[0]
        b["assignee"] = os.environ.get("LC_SPAWNID") or role
        b["state"] = "in_progress"
        self._record_history(b["id"], State.IN_PROGRESS)
        return self._to_node(b)

    def history(self, tid):
        return list(self._history.get(tid, []))

    def create_step(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None, description=None, attention=False):
        b = self._new_record(
            title=title,
            type="step",
            parent=parent,
            labels=labels_for(role=role, step=step, project=project, goal=goal,
                              attention=attention),
            description=description,
        )
        tid = b["id"]
        self._records[tid] = b
        self._deps[tid] = set()
        if deps:
            for dep in deps:
                self.dep_add(tid, dep)
        return tid

    def edit_node(self, tid, *, title=None, description=None, goal=None, project=None,
                  parent=None, workflow=None):
        b = self._get(tid)
        if title is not None:
            b["title"] = title
        if description is not None:
            b["description"] = description
        if goal is not None:
            cur = self.get_node(tid).goal
            if cur:
                self.label_remove(tid, "goal:%s" % cur)
            if goal:
                self.label_add(tid, "goal:%s" % goal)
        if project is not None:
            cur = self.get_node(tid).project
            if cur:
                self.label_remove(tid, "project:%s" % cur)
            if project:
                self.label_add(tid, "project:%s" % project)
        if parent is not None:
            b["parent"] = parent
        if workflow is not None:
            b["workflow"] = workflow
        return tid

    def create_item(self, title, *, theme=None, project=None, goal=None, workflow=None):
        b = self._new_record(
            title=title,
            type="item",
            parent=theme,
            labels=labels_for(project=project, goal=goal),
            workflow=workflow,
            state="backlogged",
        )
        tid = b["id"]
        self._records[tid] = b
        return tid

    def create_theme(self, title, *, project=None, goal=None, workflow=None):
        b = self._new_record(
            title=title,
            type="theme",
            labels=labels_for(project=project, goal=goal),
            workflow=workflow,
            state="backlogged",
        )
        tid = b["id"]
        self._records[tid] = b
        return tid

    def children(self, item_id):
        return [self._to_node(b) for b in self._records.values() if b.get("parent") == item_id]

    def claimed_steps(self):
        return [self._to_node(b) for b in self._records.values() if b.get("state") == "in_progress"]

    def nodes_closed_since(self, since_date):
        result = []
        for b in self._records.values():
            if b.get("type") != "step" or b.get("state") != "done":
                continue
            closed_at = (b.get("closed_at") or "")[:10]
            if closed_at >= since_date:
                result.append(self._to_node(b))
        return result

    def last_n_closed_themes(self, n):
        themes = [
            b
            for b in self._records.values()
            if b.get("type") == "theme" and b.get("state") == "done"
        ]
        themes.sort(key=lambda b: b.get("closed_at") or "", reverse=True)
        return [self._to_node(b) for b in themes[:n]]


    def closed_unretroed_items(self):
        result = []
        for b in self._records.values():
            if b.get("type") != "item" or b.get("state") != "done":
                continue
            labels = b.get("labels") or []
            if "retro-origin" in labels or "retroed" in labels:
                continue
            result.append(self._to_node(b))
        return result

    def last_n_closed_items(self, n):
        items = [
            b for b in self._records.values()
            if b.get("type") == "item" and b.get("state") == "done"
        ]
        items.sort(key=lambda b: b.get("closed_at") or "", reverse=True)
        return [self._to_node(b) for b in items[:n]]

    def steps_at_step(self, step):
        label = "step:%s" % step
        return [self._to_node(b) for b in self._records.values()
                if b.get("type") == "step" and label in (b.get("labels") or [])]

    def delete(self, tid):
        self._records.pop(tid, None)
        self._deps.pop(tid, None)
        self._history.pop(tid, None)
