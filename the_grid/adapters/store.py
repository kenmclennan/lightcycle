"""StorePort (abstract) + BdStore (subprocess implementation): the bd adapter."""
import json
import os
import subprocess
import sys
from abc import ABC, abstractmethod

from the_grid.adapters.fsio import grid_root
from the_grid.core.tasks import task_from_bead

_BD_NOISE = ("bd --json output format will change", "beads.role not configured",
             "Fix: git config", "Or:  git config")


def _is_noise(line):
    return any(n in line for n in _BD_NOISE)


def _bd_env():
    """Env for bd calls. Inside a worker (GRID_SPAWNID set), make bd record the
    worker's UNIQUE spawnid as the claim assignee (via git's env-config override)
    so a claim's ownership is atomic - exactly one worker holds a task, and sweep
    can key liveness off assignee -> spawnid -> pid with no registry lag."""
    env = dict(os.environ)
    spawnid = env.get("GRID_SPAWNID")
    if spawnid:
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "user.name"
        env["GIT_CONFIG_VALUE_0"] = spawnid
    return env


def _bd_run(*args):
    root = grid_root()
    proc = subprocess.run(["bd", "-C", root, *args], capture_output=True, text=True, env=_bd_env())
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("bd failed: " + " ".join(args))
    err = "\n".join(l for l in proc.stderr.splitlines() if not _is_noise(l))
    if err.strip():
        sys.stderr.write(err + "\n")
    return proc.stdout


def _bd_json_run(*args):
    return json.loads(_bd_run(*args))


class StorePort(ABC):

    @abstractmethod
    def story_artifacts(self, story_id):
        """Return the artifact list for a story."""

    @abstractmethod
    def add_artifact(self, story_id, atype, value, label=None):
        """Append an artifact entry to a story's metadata."""

    @abstractmethod
    def all_tasks(self):
        """Return all tasks as domain dicts."""

    @abstractmethod
    def get_task(self, tid):
        """Return one task as a domain dict."""

    @abstractmethod
    def task_view(self, tid):
        """Return a task dict enriched with its story's artifacts."""

    @abstractmethod
    def present_types(self, task):
        """Return the set of artifact types present on the task's story."""

    @abstractmethod
    def route_to_human(self, tid, note, role):
        """Re-route a task to the human queue with a note."""

    @abstractmethod
    def closed_stories(self):
        """Return closed stories shaped for core.worklog."""

    @abstractmethod
    def ensure_beads(self):
        """Initialise the bd store if not already present."""

    @abstractmethod
    def note(self, tid, text):
        """Add a freeform note to a task."""

    @abstractmethod
    def close(self, tid, reason):
        """Close a task with a reason string."""

    @abstractmethod
    def update_metadata(self, tid, meta):
        """Replace a task's metadata dict."""

    @abstractmethod
    def label_add(self, tid, label):
        """Add a label to a task."""

    @abstractmethod
    def label_remove(self, tid, label):
        """Remove a label from a task."""

    @abstractmethod
    def update_status(self, tid, status):
        """Set a task's status."""

    @abstractmethod
    def assign(self, tid, assignee):
        """Set (or clear) a task's assignee."""

    @abstractmethod
    def dep_add(self, task_id, blocked_by):
        """Record that task_id is blocked by blocked_by."""

    @abstractmethod
    def ready_beads(self):
        """Return all ready tasks as raw bead dicts."""

    @abstractmethod
    def claim_ready(self, role):
        """Atomically claim the next ready task for role. Returns a list (0 or 1 bead)."""

    @abstractmethod
    def create_task(self, title, *, step=None, role=None, parent=None, deps=None, labels=None):
        """Create a task bead and return its id.

        step and role, if given, are encoded as for:role and step:step labels.
        deps is a list of task ids this task depends on.
        labels is a list of extra label strings.
        """

    @abstractmethod
    def create_story(self, title, *, epic=None, labels=None):
        """Create a story bead and return its id.

        epic, if given, is the parent story id.
        labels is a list of label strings.
        """

    @abstractmethod
    def children(self, story_id):
        """Return child beads of a story as raw dicts."""

    @abstractmethod
    def list_beads_by_status(self, status):
        """Return all beads with the given status as raw dicts."""

    @abstractmethod
    def history(self, tid):
        """Return the raw history list for a task."""


class BdStore(StorePort):

    def story_artifacts(self, story_id):
        arr = _bd_json_run("show", story_id, "--json")
        meta = arr[0].get("metadata") or {}
        return meta.get("artifacts") or []

    def add_artifact(self, story_id, atype, value, label=None):
        arr = _bd_json_run("show", story_id, "--json")
        meta = arr[0].get("metadata") or {}
        artifacts = meta.get("artifacts") or []
        entry = {"type": atype, "value": value}
        if label:
            entry["label"] = label
        artifacts.append(entry)
        meta["artifacts"] = artifacts
        _bd_run("update", story_id, "--metadata", json.dumps(meta))

    def all_tasks(self):
        return [task_from_bead(b) for b in _bd_json_run("list", "--json")]

    def get_task(self, tid):
        return task_from_bead(_bd_json_run("show", tid, "--json")[0])

    def task_view(self, tid):
        t = self.get_task(tid)
        if t.get("parent"):
            t["story_artifacts"] = self.story_artifacts(t["parent"])
        else:
            t["story_artifacts"] = t.get("artifacts") or []
        return t

    def present_types(self, task):
        story = task.get("parent") or task["id"]
        return {a["type"] for a in self.story_artifacts(story)}

    def route_to_human(self, tid, note, role):
        self.note(tid, note)
        if role and role != "human":
            self.label_remove(tid, "for:%s" % role)
        self.label_add(tid, "for:human")
        self.update_status(tid, "open")
        self.assign(tid, "")

    def closed_stories(self):
        beads = _bd_json_run("list", "--status", "closed", "--json")
        result = []
        for b in beads:
            if b.get("issue_type") != "story":
                continue
            result.append({
                "id": b["id"],
                "title": b.get("title", ""),
                "closed_at": b.get("closed_at"),
                "outcome": b.get("close_reason"),
                "artifacts": (b.get("metadata") or {}).get("artifacts") or [],
            })
        return result

    def ensure_beads(self):
        root = grid_root()
        if os.path.isdir(os.path.join(root, ".beads", "embeddeddolt")):
            return
        subprocess.run(["bd", "init", "--skip-agents", "--skip-hooks",
                        "--non-interactive", "--quiet"], cwd=root, check=True)

    def note(self, tid, text):
        _bd_run("note", tid, text)

    def close(self, tid, reason):
        _bd_run("close", tid, "--reason", reason)

    def update_metadata(self, tid, meta):
        _bd_run("update", tid, "--metadata", json.dumps(meta))

    def label_add(self, tid, label):
        _bd_run("label", "add", tid, label)

    def label_remove(self, tid, label):
        _bd_run("label", "remove", tid, label)

    def update_status(self, tid, status):
        _bd_run("update", tid, "--status", status)

    def assign(self, tid, assignee):
        _bd_run("assign", tid, assignee)

    def dep_add(self, task_id, blocked_by):
        _bd_run("dep", "add", task_id, "--blocked-by", blocked_by)

    def ready_beads(self):
        return _bd_json_run("ready", "--json")

    def claim_ready(self, role):
        return _bd_json_run("ready", "--label", "for:%s" % role, "--claim", "--json")

    def create_task(self, title, *, step=None, role=None, parent=None, deps=None, labels=None):
        args = ["create", title, "-t", "task"]
        all_labels = list(labels or [])
        if step and role:
            all_labels = ["for:%s,step:%s" % (role, step)] + all_labels
        elif role:
            all_labels = ["for:%s" % role] + all_labels
        elif step:
            all_labels = ["step:%s" % step] + all_labels
        if all_labels:
            args += ["-l", ",".join(all_labels)]
        if parent:
            args += ["--parent", parent]
        if deps:
            for dep in deps:
                args += ["--deps", dep]
        args += ["--json"]
        return _bd_json_run(*args)["id"]

    def create_story(self, title, *, epic=None, labels=None):
        args = ["create", title, "-t", "story"]
        if epic:
            args += ["--parent", epic]
        if labels:
            args += ["-l", ",".join(labels)]
        args += ["--json"]
        return _bd_json_run(*args)["id"]

    def children(self, story_id):
        return _bd_json_run("children", story_id, "--json")

    def list_beads_by_status(self, status):
        return _bd_json_run("list", "--status", status, "--json")

    def history(self, tid):
        return _bd_json_run("history", tid, "--json")
