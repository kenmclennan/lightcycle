"""BdStore: the subprocess StorePort implementation (the bd adapter)."""
import json
import os
import subprocess
import sys

from the_grid.core.tasks import task_from_bead
from the_grid.ports.store import StorePort

_BD_NOISE = ("bd --json output format will change", "beads.role not configured",
             "Fix: git config", "Or:  git config")


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
        return meta.get("artifacts") or []

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
        return [task_from_bead(b) for b in self._json("list", "--json")]

    def get_task(self, tid):
        return task_from_bead(self._json("show", tid, "--json")[0])

    def task_view(self, tid):
        t = self.get_task(tid)
        t["story_artifacts"] = self.story_artifacts(t.parent) if t.parent else t.artifacts
        return t

    def present_types(self, task):
        story = task.parent or task.id
        return {a["type"] for a in self.story_artifacts(story)}

    def route_to_human(self, tid, note, role):
        self.note(tid, note)
        if role and role != "human":
            self.label_remove(tid, "for:%s" % role)
        self.label_add(tid, "for:human")
        self.update_status(tid, "open")
        self.assign(tid, "")

    def closed_stories(self):
        beads = self._json("list", "--status", "closed", "--json")
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
        root = self._config.grid_root()
        if os.path.isdir(os.path.join(root, ".beads", "embeddeddolt")):
            return
        subprocess.run(["bd", "init", "--skip-agents", "--skip-hooks",
                        "--non-interactive", "--quiet"], cwd=root, check=True)

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

    def ready_beads(self):
        return self._json("ready", "--json")

    def claim_ready(self, role):
        return self._json("ready", "--label", "for:%s" % role, "--claim", "--json")

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
        return self._json(*args)["id"]

    def create_story(self, title, *, epic=None, labels=None):
        args = ["create", title, "-t", "story"]
        if epic:
            args += ["--parent", epic]
        if labels:
            args += ["-l", ",".join(labels)]
        args += ["--json"]
        return self._json(*args)["id"]

    def children(self, story_id):
        return [task_from_bead(b) for b in self._json("children", story_id, "--json")]

    def list_beads_by_status(self, status):
        return self._json("list", "--status", status, "--json")

    def history(self, tid):
        return self._json("history", tid, "--json")
