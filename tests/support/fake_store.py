import datetime
import os
import uuid

from the_grid.ports.store import StorePort
from the_grid.domain.work import Artifact, Status, Task, TaskView


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


def record_to_task(record):
    labels = record.get("labels") or []
    role = _label_value(labels, "for:")
    meta = record.get("metadata") or {}
    return Task(
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
        epic=meta.get("epic"),
        since=meta.get("since"),
        fired_at=meta.get("fired_at"),
        closed_at=record.get("closed_at"),
        attention="attention" in labels,
        model=meta.get("model"),
    )


class FakeStore(StorePort):
    def __init__(self):
        self._records = {}
        self._deps = {}
        self._history = {}

    def _new_record(self, **fields):
        b = {
            "id": _new_id(),
            "title": "",
            "type": "task",
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
            raise KeyError("task not found: %s" % tid)

    def story_artifacts(self, story_id):
        b = self._get(story_id)
        return [Artifact.from_dict(a) for a in ((b.get("metadata") or {}).get("artifacts") or [])]

    def add_artifact(self, story_id, atype, value, label=None):
        b = self._get(story_id)
        meta = dict(b.get("metadata") or {})
        artifacts = list(meta.get("artifacts") or [])
        entry = {"type": atype, "value": value}
        if label:
            entry["label"] = label
        artifacts.append(entry)
        meta["artifacts"] = artifacts
        b["metadata"] = meta

    def all_tasks(self):
        return [record_to_task(b) for b in self._records.values()
                if b.get("status") != "closed"]

    def get_task(self, tid):
        return record_to_task(self._get(tid))

    def task_view(self, tid):
        t = self.get_task(tid)
        arts = self.story_artifacts(t.parent) if t.parent else t.artifacts
        return TaskView(task=t, story_artifacts=list(arts))

    def present_types(self, task):
        story = task.parent or task.id
        return {a.type for a in self.story_artifacts(story)}

    def reassign(self, tid, role):
        cur = self.get_task(tid).role
        if cur and cur != role:
            self.label_remove(tid, "for:%s" % cur)
        self.label_add(tid, "for:%s" % role)
        self.update_status(tid, "open")
        self.assign(tid, "")

    def route_to_human(self, tid, note):
        self.note(tid, note)
        self.reassign(tid, "human")

    def closed_stories(self):
        result = []
        for b in self._records.values():
            if b.get("type") != "story" or b.get("status") != "closed":
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

    def close(self, tid, reason):
        b = self._get(tid)
        b["status"] = "closed"
        b["outcome"] = reason
        b["closed_at"] = datetime.datetime.now().isoformat()
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
        self._history.setdefault(tid, []).insert(0, {"Issue": {"status": status}})

    def assign(self, tid, assignee):
        self._get(tid)["assignee"] = assignee or None

    def dep_add(self, task_id, blocked_by):
        if task_id not in self._deps:
            self._deps[task_id] = set()
        self._deps[task_id].add(blocked_by)
        blocker = self._records.get(blocked_by)
        if blocker and blocker.get("status") != "closed":
            b = self._get(task_id)
            b["dep_count"] = (b.get("dep_count") or 0) + 1

    def _ready_records(self):
        return [
            b
            for b in self._records.values()
            if b.get("status") == "open"
            and not b.get("assignee")
            and not (b.get("dep_count") or 0)
            and b.get("type") == "task"
        ]

    def ready_tasks(self):
        return [record_to_task(b) for b in self._ready_records()]

    def claim_ready(self, role):
        candidates = [
            b for b in self._ready_records() if "for:%s" % role in (b.get("labels") or [])
        ]
        if not candidates:
            return None
        b = candidates[0]
        b["assignee"] = os.environ.get("GRID_SPAWNID") or role
        b["status"] = "in_progress"
        return record_to_task(b)

    def history(self, tid):
        return self._history.get(tid, [])

    def create_task(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None, description=None, attention=False):
        b = self._new_record(
            title=title,
            type="task",
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

    def edit_task(self, tid, *, title=None, description=None, goal=None, project=None, parent=None):
        b = self._get(tid)
        if title is not None:
            b["title"] = title
        if description is not None:
            b["description"] = description
        if goal is not None:
            cur = self.get_task(tid).goal
            if cur:
                self.label_remove(tid, "goal:%s" % cur)
            if goal:
                self.label_add(tid, "goal:%s" % goal)
        if project is not None:
            cur = self.get_task(tid).project
            if cur:
                self.label_remove(tid, "project:%s" % cur)
            if project:
                self.label_add(tid, "project:%s" % project)
        if parent is not None:
            b["parent"] = parent

    def create_story(self, title, *, epic=None, project=None, goal=None):
        b = self._new_record(
            title=title,
            type="story",
            parent=epic,
            labels=labels_for(project=project, goal=goal),
        )
        tid = b["id"]
        self._records[tid] = b
        return tid

    def create_epic(self, title, *, project=None, goal=None):
        b = self._new_record(
            title=title,
            type="epic",
            labels=labels_for(project=project, goal=goal),
        )
        tid = b["id"]
        self._records[tid] = b
        return tid

    def children(self, story_id):
        return [record_to_task(b) for b in self._records.values() if b.get("parent") == story_id]

    def claimed_tasks(self):
        return [record_to_task(b) for b in self._records.values() if b.get("status") == "in_progress"]

    def tasks_closed_since(self, since_date):
        result = []
        for b in self._records.values():
            if b.get("type") != "task" or b.get("status") != "closed":
                continue
            closed_at = (b.get("closed_at") or "")[:10]
            if closed_at >= since_date:
                result.append(record_to_task(b))
        return result

    def last_n_closed_epics(self, n):
        epics = [
            b
            for b in self._records.values()
            if b.get("type") == "story"
            and b.get("status") == "closed"
            and b.get("parent") is None
        ]
        epics.sort(key=lambda b: b.get("closed_at") or "", reverse=True)
        return [record_to_task(b) for b in epics[:n]]

    def epics_closed_since(self, since_date_str):
        result = []
        for b in self._records.values():
            if b.get("type") != "story" or b.get("status") != "closed":
                continue
            if b.get("parent") is not None:
                continue
            if "retro-origin" in (b.get("labels") or []):
                continue
            closed_at = (b.get("closed_at") or "")[:10]
            if closed_at >= since_date_str:
                result.append(record_to_task(b))
        return result

    def tasks_at_step(self, step):
        label = "step:%s" % step
        return [record_to_task(b) for b in self._records.values()
                if b.get("type") == "task" and label in (b.get("labels") or [])]

    def delete(self, tid):
        self._records.pop(tid, None)
        self._deps.pop(tid, None)
        self._history.pop(tid, None)
