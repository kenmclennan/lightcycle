"""BdStore: the subprocess StorePort implementation (the bd adapter)."""
import json
import os
import subprocess
import sys

from the_grid.adapters.bead import bead_to_task, labels_for
from the_grid.domain.work import Artifact, TaskView
from the_grid.ports.store import StorePort

_BD_NOISE = ("bd --json output format will change", "beads.role not configured",
             "Fix: git config", "Or:  git config")

_UNLIMITED = ("--limit", "0")


def _is_noise(line):
    return any(n in line for n in _BD_NOISE)


class BdStore(StorePort):

    def __init__(self, config):
        self._config = config

    def _env(self):
        """Env for bd calls. Inside a worker (spawn id set), make bd record the
        worker's UNIQUE spawnid as the claim assignee (via git's env-config override)
        so a claim's ownership is atomic - exactly one worker holds a task, and sweep
        can key liveness off assignee -> spawnid -> pid with no registry lag."""
        env = self._config.base_env()
        spawnid = self._config.spawn_id()
        if spawnid:
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "user.name"
            env["GIT_CONFIG_VALUE_0"] = spawnid
        return env

    def _run(self, *args):
        root = self._config.grid_root()
        proc = subprocess.run(["bd", "-C", root, *args], capture_output=True, text=True, env=self._env())
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            raise SystemExit("bd failed: " + " ".join(args))
        err = "\n".join(l for l in proc.stderr.splitlines() if not _is_noise(l))
        if err.strip():
            sys.stderr.write(err + "\n")
        return proc.stdout

    def _json(self, *args):
        return json.loads(self._run(*args))

    def story_artifacts(self, story_id):
        arr = self._json("show", story_id, "--json")
        meta = arr[0].get("metadata") or {}
        return [Artifact.from_dict(a) for a in (meta.get("artifacts") or [])]

    def add_artifact(self, story_id, atype, value, label=None):
        arr = self._json("show", story_id, "--json")
        meta = arr[0].get("metadata") or {}
        artifacts = meta.get("artifacts") or []
        entry = {"type": atype, "value": value}
        if label:
            entry["label"] = label
        artifacts.append(entry)
        meta["artifacts"] = artifacts
        self._run("update", story_id, "--metadata", json.dumps(meta))

    def all_tasks(self):
        return [bead_to_task(b) for b in self._json("list", *_UNLIMITED, "--json")]

    def get_task(self, tid):
        return bead_to_task(self._json("show", tid, "--json")[0])

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
        beads = self._json("list", "--status", "closed", *_UNLIMITED, "--json")
        result = []
        for b in beads:
            if b.get("issue_type") != "story":
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

    def ensure_store(self):
        root = self._config.grid_root()
        if os.path.isdir(os.path.join(root, ".beads", "embeddeddolt")):
            return
        subprocess.run(["bd", "init", "--skip-agents", "--skip-hooks",
                        "--non-interactive", "--quiet"], cwd=root, check=True)

    def reclaim(self, tid):
        self.update_status(tid, "open")
        self.assign(tid, "")

    def note(self, tid, text):
        self._run("note", tid, text)

    def close(self, tid, reason):
        self._run("close", tid, "--reason", reason)

    def update_metadata(self, tid, meta):
        self._run("update", tid, "--metadata", json.dumps(meta))

    def label_add(self, tid, label):
        self._run("label", "add", tid, label)

    def label_remove(self, tid, label):
        self._run("label", "remove", tid, label)

    def update_status(self, tid, status):
        self._run("update", tid, "--status", status)

    def assign(self, tid, assignee):
        self._run("assign", tid, assignee)

    def dep_add(self, task_id, blocked_by):
        self._run("dep", "add", task_id, "--blocked-by", blocked_by)

    def ready_tasks(self):
        return [bead_to_task(b) for b in self._json("ready", "--json")]

    def claim_ready(self, role):
        arr = self._json("ready", "--label", "for:%s" % role, "--claim", "--json")
        return bead_to_task(arr[0]) if arr else None

    def create_task(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None, description=None):
        args = ["create", title, "-t", "task"]
        labels = labels_for(role=role, step=step, project=project, goal=goal)
        if labels:
            args += ["-l", ",".join(labels)]
        if parent:
            args += ["--parent", parent]
        if deps:
            for dep in deps:
                args += ["--deps", dep]
        if description:
            args += ["-d", description]
        args += ["--json"]
        return self._json(*args)["id"]

    def edit_task(self, tid, *, title=None, description=None, goal=None, project=None, parent=None):
        update_args = ["update", tid]
        if title is not None:
            update_args += ["--title", title]
        if description is not None:
            update_args += ["-d", description]
        if parent is not None:
            update_args += ["--parent", parent]
        if title is not None or description is not None or parent is not None:
            self._run(*update_args)
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

    def create_story(self, title, *, epic=None, project=None, goal=None):
        args = ["create", title, "-t", "story"]
        if epic:
            args += ["--parent", epic]
        labels = labels_for(project=project, goal=goal)
        if labels:
            args += ["-l", ",".join(labels)]
        args += ["--json"]
        return self._json(*args)["id"]

    def children(self, story_id):
        return [bead_to_task(b) for b in self._json("children", story_id, "--json")]

    def claimed_tasks(self):
        return [bead_to_task(b) for b in self._json("list", "--status", "in_progress", *_UNLIMITED, "--json")]

    def history(self, tid):
        return self._json("history", tid, "--json")

    def tasks_closed_since(self, since_date):
        beads = self._json("list", "--status", "closed", *_UNLIMITED, "--json")
        result = []
        for b in beads:
            if b.get("issue_type") != "task":
                continue
            closed_at = (b.get("closed_at") or "")[:10]
            if closed_at >= since_date:
                result.append(bead_to_task(b))
        return result

    def last_n_closed_epics(self, n):
        beads = self._json("list", "--status", "closed", *_UNLIMITED, "--json")
        epics = [
            b for b in beads
            if b.get("issue_type") == "story"
            and not b.get("parent")
        ]
        epics.sort(key=lambda b: b.get("closed_at") or "", reverse=True)
        return [bead_to_task(b) for b in epics[:n]]
