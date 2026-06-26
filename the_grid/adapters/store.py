"""The bd adapter: the only caller of the bd CLI, plus the bd-backed data ops."""
import json
import os
import subprocess
import sys

from the_grid.adapters.fsio import grid_root
from the_grid.core.tasks import task_from_bead

# bd prints assorted advisory noise to stderr; filter the known-benign lines.
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


def bd(*args):
    root = grid_root()
    proc = subprocess.run(["bd", "-C", root, *args], capture_output=True, text=True, env=_bd_env())
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("bd failed: " + " ".join(args))
    err = "\n".join(l for l in proc.stderr.splitlines() if not _is_noise(l))
    if err.strip():
        sys.stderr.write(err + "\n")
    return proc.stdout


def bd_json(*args):
    return json.loads(bd(*args))


def ensure_beads():
    root = grid_root()
    if os.path.isdir(os.path.join(root, ".beads", "embeddeddolt")):
        return
    subprocess.run(["bd", "init", "--skip-agents", "--skip-hooks",
                    "--non-interactive", "--quiet"], cwd=root, check=True)


def story_artifacts(story_id):
    arr = bd_json("show", story_id, "--json")
    meta = arr[0].get("metadata") or {}
    return meta.get("artifacts") or []


def add_artifact(story_id, atype, value, label=None):
    arr = bd_json("show", story_id, "--json")
    meta = arr[0].get("metadata") or {}
    artifacts = meta.get("artifacts") or []
    entry = {"type": atype, "value": value}
    if label:
        entry["label"] = label
    artifacts.append(entry)
    meta["artifacts"] = artifacts
    bd("update", story_id, "--metadata", json.dumps(meta))


def all_tasks():
    return [task_from_bead(b) for b in bd_json("list", "--json")]


def get_task(tid):
    return task_from_bead(bd_json("show", tid, "--json")[0])


def task_view(tid):
    t = get_task(tid)
    if t.get("parent"):
        t["story_artifacts"] = story_artifacts(t["parent"])
    else:
        t["story_artifacts"] = t.get("artifacts") or []
    return t


def present_types(task):
    story = task.get("parent") or task["id"]
    return {a["type"] for a in story_artifacts(story)}


def route_to_human(tid, note, role):
    bd("note", tid, note)
    if role and role != "human":
        bd("label", "remove", tid, "for:%s" % role)
    bd("label", "add", tid, "for:human")
    bd("update", tid, "--status", "open")
    bd("assign", tid, "")
