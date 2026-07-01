"""FakeStore: in-memory StorePort for tests. No subprocess, no bd."""
import datetime
import os
import uuid

from the_grid.adapters.bead import bead_to_task, labels_for
from the_grid.ports.store import StorePort
from the_grid.domain.work import Artifact


def _new_id():
    return "fake-" + uuid.uuid4().hex[:8]


class FakeStore(StorePort):

    def __init__(self):
        self._beads = {}   # id -> raw bead dict
        self._deps = {}    # task_id -> set of blocking dep ids
        self._history = {} # id -> list of {"Issue": {"status": ...}} (newest first)

    def _new_bead(self, **fields):
        b = {
            "id": _new_id(), "title": "", "issue_type": "task",
            "labels": [], "status": "open", "assignee": None,
            "metadata": {}, "parent": None, "dependency_count": 0,
            "close_reason": None, "notes": None, "closed_at": None,
        }
        b.update(fields)
        return b

    def _get(self, tid):
        try:
            return self._beads[tid]
        except KeyError:
            raise KeyError("bead not found: %s" % tid)

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
        return [bead_to_task(b) for b in self._beads.values()]

    def get_task(self, tid):
        return bead_to_task(self._get(tid))

    def task_view(self, tid):
        t = self.get_task(tid)
        view = t.as_dict()
        arts = self.story_artifacts(t.parent) if t.parent else t.artifacts
        view["story_artifacts"] = [a.as_dict() for a in arts]
        return view

    def present_types(self, task):
        story = task.parent or task.id
        return {a.type for a in self.story_artifacts(story)}

    def route_to_human(self, tid, note, role):
        self.note(tid, note)
        if role and role != "human":
            self.label_remove(tid, "for:%s" % role)
        self.label_add(tid, "for:human")
        self.update_status(tid, "open")
        self.assign(tid, "")

    def closed_stories(self):
        result = []
        for b in self._beads.values():
            if b.get("issue_type") != "story" or b.get("status") != "closed":
                continue
            result.append({
                "id": b["id"],
                "title": b.get("title", ""),
                "closed_at": b.get("closed_at"),
                "outcome": b.get("close_reason"),
                "artifacts": [Artifact.from_dict(a)
                              for a in ((b.get("metadata") or {}).get("artifacts") or [])],
            })
        return result

    def ensure_beads(self):
        pass

    def note(self, tid, text):
        b = self._get(tid)
        existing = b.get("notes")
        b["notes"] = (existing + "\n" + text) if existing else text

    def close(self, tid, reason):
        b = self._get(tid)
        b["status"] = "closed"
        b["close_reason"] = reason
        b["closed_at"] = datetime.datetime.now().isoformat()
        for other_id, blockers in self._deps.items():
            if tid in blockers:
                other = self._beads.get(other_id)
                if other and other.get("status") != "closed":
                    other["dependency_count"] = max(0, (other.get("dependency_count") or 0) - 1)

    def update_metadata(self, tid, meta):
        self._get(tid)["metadata"] = dict(meta)

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
        blocker = self._beads.get(blocked_by)
        if blocker and blocker.get("status") != "closed":
            b = self._get(task_id)
            b["dependency_count"] = (b.get("dependency_count") or 0) + 1

    def _ready_bead_dicts(self):
        return [
            b for b in self._beads.values()
            if b.get("status") == "open"
            and not b.get("assignee")
            and not (b.get("dependency_count") or 0)
            and b.get("issue_type") == "task"
        ]

    def ready_tasks(self):
        return [bead_to_task(b) for b in self._ready_bead_dicts()]

    def claim_ready(self, role):
        candidates = [b for b in self._ready_bead_dicts() if "for:%s" % role in (b.get("labels") or [])]
        if not candidates:
            return None
        b = candidates[0]
        b["assignee"] = os.environ.get("GRID_SPAWNID") or role
        b["status"] = "in_progress"
        return bead_to_task(b)

    def history(self, tid):
        return self._history.get(tid, [])

    def create_task(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None):
        b = self._new_bead(
            title=title,
            issue_type="task",
            parent=parent,
            labels=labels_for(role=role, step=step, project=project, goal=goal),
        )
        tid = b["id"]
        self._beads[tid] = b
        self._deps[tid] = set()
        if deps:
            for dep in deps:
                self.dep_add(tid, dep)
        return tid

    def create_story(self, title, *, epic=None, project=None, goal=None):
        b = self._new_bead(
            title=title,
            issue_type="story",
            parent=epic,
            labels=labels_for(project=project, goal=goal),
        )
        tid = b["id"]
        self._beads[tid] = b
        return tid

    def children(self, story_id):
        return [bead_to_task(b) for b in self._beads.values() if b.get("parent") == story_id]

    def list_beads_by_status(self, status):
        return [b for b in self._beads.values() if b.get("status") == status]
