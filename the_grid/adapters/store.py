import dataclasses
import json
import os
import subprocess
import sys

from the_grid.adapters.bead import bead_to_task, labels_for
from the_grid.domain.work import Artifact, ExternalRef, TaskView
from the_grid.ports.store import StorePort

_BD_NOISE = (
    "bd --json output format will change",
    "beads.role not configured",
    "Fix: git config",
    "Or:  git config",
)

_UNLIMITED = ("--limit", "0")


def _is_noise(line):
    return any(n in line for n in _BD_NOISE)


class BdStore(StorePort):
    def __init__(self, config):
        self._config = config
        self._prefix_cache = None

    def _env(self):
        env = self._config.base_env()
        spawnid = self._config.spawn_id()
        if spawnid:
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "user.name"
            env["GIT_CONFIG_VALUE_0"] = spawnid
        return env

    def _run(self, *args):
        root = self._config.grid_root()
        proc = subprocess.run(
            ["bd", "-C", root, *args], capture_output=True, text=True, env=self._env()
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            raise SystemExit("bd failed: " + " ".join(args))
        err = "\n".join(l for l in proc.stderr.splitlines() if not _is_noise(l))
        if err.strip():
            sys.stderr.write(err + "\n")
        return proc.stdout

    def _json(self, *args):
        return json.loads(self._run(*args))

    def _prefix(self):
        if self._prefix_cache is None:
            self._prefix_cache = self._discover_prefix()
        return self._prefix_cache

    def _discover_prefix(self):
        data = self._json("config", "get", "issue_prefix", "--json")
        prefix = data.get("value")
        if not prefix:
            raise SystemExit("could not determine bd issue prefix: " + json.dumps(data))
        return prefix

    def _short(self, bead_id):
        if bead_id is None:
            return None
        return ExternalRef(self._prefix(), bead_id).short

    def _qualify(self, tid):
        return ExternalRef.qualify(self._prefix(), tid)

    def _strip_task(self, task):
        return dataclasses.replace(
            task,
            id=self._short(task.id),
            parent=self._short(task.parent),
            epic=self._short(task.epic),
        )

    def story_artifacts(self, story_id):
        arr = self._json("show", self._qualify(story_id), "--json")
        meta = arr[0].get("metadata") or {}
        return [Artifact.from_dict(a) for a in (meta.get("artifacts") or [])]

    def add_artifact(self, story_id, atype, value, label=None):
        arr = self._json("show", self._qualify(story_id), "--json")
        meta = arr[0].get("metadata") or {}
        artifacts = meta.get("artifacts") or []
        entry = {"type": atype, "value": value}
        if label:
            entry["label"] = label
        artifacts.append(entry)
        meta["artifacts"] = artifacts
        self._run("update", self._qualify(story_id), "--metadata", json.dumps(meta))

    def all_tasks(self):
        return [self._strip_task(bead_to_task(b)) for b in self._json("list", *_UNLIMITED, "--json")]

    def get_task(self, tid):
        return self._strip_task(bead_to_task(self._json("show", self._qualify(tid), "--json")[0]))

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
            result.append(
                {
                    "id": self._short(b["id"]),
                    "title": b.get("title", ""),
                    "closed_at": b.get("closed_at"),
                    "outcome": b.get("close_reason"),
                    "artifacts": [
                        Artifact.from_dict(a)
                        for a in ((b.get("metadata") or {}).get("artifacts") or [])
                    ],
                }
            )
        return result

    def ensure_store(self):
        root = self._config.grid_root()
        if os.path.isdir(os.path.join(root, ".beads", "embeddeddolt")):
            return
        subprocess.run(
            ["bd", "init", "--skip-agents", "--skip-hooks", "--non-interactive", "--quiet"],
            cwd=root,
            check=True,
        )

    def reclaim(self, tid):
        self.update_status(tid, "open")
        self.assign(tid, "")

    def note(self, tid, text):
        self._run("note", self._qualify(tid), text)

    def close(self, tid, reason):
        self._run("close", self._qualify(tid), "--reason", reason)

    def update_metadata(self, tid, meta):
        self._run("update", self._qualify(tid), "--metadata", json.dumps(meta))

    def label_add(self, tid, label):
        self._run("label", "add", self._qualify(tid), label)

    def label_remove(self, tid, label):
        self._run("label", "remove", self._qualify(tid), label)

    def update_status(self, tid, status):
        self._run("update", self._qualify(tid), "--status", status)

    def assign(self, tid, assignee):
        self._run("assign", self._qualify(tid), assignee)

    def dep_add(self, task_id, blocked_by):
        self._run("dep", "add", self._qualify(task_id), "--blocked-by", self._qualify(blocked_by))

    def ready_tasks(self):
        return [self._strip_task(bead_to_task(b)) for b in self._json("ready", "--json")]

    def claim_ready(self, role):
        arr = self._json("ready", "--label", "for:%s" % role, "--claim", "--json")
        return self._strip_task(bead_to_task(arr[0])) if arr else None

    def create_task(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None, description=None, attention=False):
        args = ["create", title, "-t", "task"]
        labels = labels_for(role=role, step=step, project=project, goal=goal, attention=attention)
        if labels:
            args += ["-l", ",".join(labels)]
        if parent:
            args += ["--parent", self._qualify(parent)]
        if deps:
            for dep in deps:
                args += ["--deps", self._qualify(dep)]
        if description:
            args += ["-d", description]
        args += ["--json"]
        return self._short(self._json(*args)["id"])

    def edit_task(self, tid, *, title=None, description=None, goal=None, project=None, parent=None):
        qtid = self._qualify(tid)
        update_args = ["update", qtid]
        if title is not None:
            update_args += ["--title", title]
        if description is not None:
            update_args += ["-d", description]
        if parent is not None:
            update_args += ["--parent", self._qualify(parent)]
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
            args += ["--parent", self._qualify(epic)]
        labels = labels_for(project=project, goal=goal)
        if labels:
            args += ["-l", ",".join(labels)]
        args += ["--json"]
        return self._short(self._json(*args)["id"])

    def children(self, story_id):
        return [self._strip_task(bead_to_task(b)) for b in self._json("children", self._qualify(story_id), "--json")]

    def claimed_tasks(self):
        return [
            self._strip_task(bead_to_task(b))
            for b in self._json("list", "--status", "in_progress", *_UNLIMITED, "--json")
        ]

    def history(self, tid):
        return self._json("history", self._qualify(tid), "--json")

    def tasks_closed_since(self, since_date):
        beads = self._json("list", "--status", "closed", *_UNLIMITED, "--json")
        result = []
        for b in beads:
            if b.get("issue_type") != "task":
                continue
            closed_at = (b.get("closed_at") or "")[:10]
            if closed_at >= since_date:
                result.append(self._strip_task(bead_to_task(b)))
        return result

    def last_n_closed_epics(self, n):
        beads = self._json("list", "--status", "closed", *_UNLIMITED, "--json")
        epics = [b for b in beads if b.get("issue_type") == "story" and not b.get("parent")]
        epics.sort(key=lambda b: b.get("closed_at") or "", reverse=True)
        return [self._strip_task(bead_to_task(b)) for b in epics[:n]]

    def epics_closed_since(self, since_date_str):
        beads = self._json("list", "--status", "closed", *_UNLIMITED, "--json")
        result = []
        for b in beads:
            if b.get("issue_type") != "story" or b.get("parent"):
                continue
            if "retro-origin" in (b.get("labels") or []):
                continue
            closed_at = (b.get("closed_at") or "")[:10]
            if closed_at >= since_date_str:
                result.append(self._strip_task(bead_to_task(b)))
        return result

    def tasks_at_step(self, step):
        open_beads = self._json("list", *_UNLIMITED, "--json")
        closed_beads = self._json("list", "--status", "closed", *_UNLIMITED, "--json")
        label = "step:%s" % step
        return [bead_to_task(b) for b in open_beads + closed_beads
                if b.get("issue_type") == "task" and label in (b.get("labels") or [])]

    def delete(self, tid):
        self._run("delete", self._qualify(tid), "--force")
