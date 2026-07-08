import datetime
import os
import uuid

from lightcycle.ports.store import StorePort
from lightcycle.domain.work import Artifact, Status, Node, NodeView


def _new_id():
    return "fake-" + uuid.uuid4().hex[:8]


def _label_value(labels, prefix):
    for l in labels:
        if l.startswith(prefix):
            return l[len(prefix):]
    return None


def _status_of(record, role):
    status = record.get("status")
    if status == "closed":
        return Status.DONE
    if record.get("assignee") or status == "in_progress":
        return Status.IN_PROGRESS
    if role == "human":
        return Status.NEEDS_HUMAN
    return Status.READY


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
    return Node(
        id=record["id"],
        title=record.get("title", ""),
        type=record.get("type"),
        parent=record.get("parent"),
        role=role,
        step=_label_value(labels, "step:"),
        status=_status_of(record, role),
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
        state=meta.get("state"),
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
            "status": "open",
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

    def all_nodes(self):
        return [record_to_node(b) for b in self._records.values()
                if b.get("status") != "closed"]

    def get_node(self, tid):
        return record_to_node(self._get(tid))

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
        self.update_status(tid, "open")
        self.assign(tid, "")

    def route_to_human(self, tid, note):
        self.note(tid, note)
        self.reassign(tid, "human")

    def closed_items(self):
        result = []
        for b in self._records.values():
            if b.get("type") != "item" or b.get("status") != "closed":
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
        self.update_status(tid, "open")
        self.assign(tid, "")

    def note(self, tid, text):
        b = self._get(tid)
        existing = b.get("notes")
        b["notes"] = (existing + "\n" + text) if existing else text

    def set_notes(self, tid, text):
        self._get(tid)["notes"] = text or None

    def close(self, tid, reason):
        b = self._get(tid)
        b["status"] = "closed"
        b["outcome"] = reason
        b["closed_at"] = datetime.datetime.now().isoformat()
        self._record_history(tid, Status.DONE)
        for other_id, blockers in self._deps.items():
            if tid in blockers:
                other = self._records.get(other_id)
                if other and other.get("status") != "closed":
                    other["dep_count"] = max(0, (other.get("dep_count") or 0) - 1)

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

    def update_status(self, tid, status):
        self._get(tid)["status"] = status
        self._record_history(tid, status)

    def _record_history(self, tid, status):
        self._history.setdefault(tid, []).append((str(status), self._now()))

    def assign(self, tid, assignee):
        self._get(tid)["assignee"] = assignee or None

    def dep_add(self, node_id, blocked_by):
        if node_id not in self._deps:
            self._deps[node_id] = set()
        self._deps[node_id].add(blocked_by)
        blocker = self._records.get(blocked_by)
        if blocker and blocker.get("status") != "closed":
            b = self._get(node_id)
            b["dep_count"] = (b.get("dep_count") or 0) + 1

    def _ready_records(self):
        return [
            b
            for b in self._records.values()
            if b.get("status") == "open"
            and not b.get("assignee")
            and not (b.get("dep_count") or 0)
            and b.get("type") == "step"
        ]

    def ready_steps(self):
        return [record_to_node(b) for b in self._ready_records()]

    def claim_ready(self, role):
        candidates = [
            b for b in self._ready_records() if "for:%s" % role in (b.get("labels") or [])
        ]
        if not candidates:
            return None
        b = candidates[0]
        b["assignee"] = os.environ.get("LC_SPAWNID") or role
        b["status"] = "in_progress"
        self._record_history(b["id"], Status.IN_PROGRESS)
        return record_to_node(b)

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
                  parent=None, workflow=None, state=None):
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
        if state is not None:
            meta = dict(b.get("metadata") or {})
            meta["state"] = state
            b["metadata"] = meta

    def create_item(self, title, *, theme=None, project=None, goal=None, workflow=None):
        b = self._new_record(
            title=title,
            type="item",
            parent=theme,
            labels=labels_for(project=project, goal=goal),
            workflow=workflow,
            metadata={"state": "todo"},
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
        )
        tid = b["id"]
        self._records[tid] = b
        return tid

    def children(self, item_id):
        return [record_to_node(b) for b in self._records.values() if b.get("parent") == item_id]

    def claimed_steps(self):
        return [record_to_node(b) for b in self._records.values() if b.get("status") == "in_progress"]

    def nodes_closed_since(self, since_date):
        result = []
        for b in self._records.values():
            if b.get("type") != "step" or b.get("status") != "closed":
                continue
            closed_at = (b.get("closed_at") or "")[:10]
            if closed_at >= since_date:
                result.append(record_to_node(b))
        return result

    def last_n_closed_themes(self, n):
        themes = [
            b
            for b in self._records.values()
            if b.get("type") == "theme" and b.get("status") == "closed"
        ]
        themes.sort(key=lambda b: b.get("closed_at") or "", reverse=True)
        return [record_to_node(b) for b in themes[:n]]


    def items_closed_since(self, since_date):
        result = []
        for b in self._records.values():
            if b.get("type") != "item" or b.get("status") != "closed":
                continue
            if "retro-origin" in (b.get("labels") or []):
                continue
            if (b.get("closed_at") or "")[:10] >= since_date:
                result.append(record_to_node(b))
        return result

    def last_n_closed_items(self, n):
        items = [
            b for b in self._records.values()
            if b.get("type") == "item" and b.get("status") == "closed"
        ]
        items.sort(key=lambda b: b.get("closed_at") or "", reverse=True)
        return [record_to_node(b) for b in items[:n]]

    def steps_at_step(self, step):
        label = "step:%s" % step
        return [record_to_node(b) for b in self._records.values()
                if b.get("type") == "step" and label in (b.get("labels") or [])]

    def delete(self, tid):
        self._records.pop(tid, None)
        self._deps.pop(tid, None)
        self._history.pop(tid, None)
