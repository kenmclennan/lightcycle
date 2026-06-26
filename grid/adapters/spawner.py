"""Worker process lifecycle: spawn a claude -p worker (or a GRID_SPAWN_CMD stub)."""
import os
import shlex
import subprocess
import sys
import time
import uuid

from grid.adapters.fsio import grid_root, parse_agent
from grid.adapters.workers import workers_state, write_workers


def spawn_worker(role):
    root = grid_root()
    agent = parse_agent(role)
    if agent is None:
        sys.stderr.write("no agent definition for role %s\n" % role)
        return None
    model = agent["meta"].get("model")
    if not model:
        sys.stderr.write("agent %s has no 'model' in frontmatter\n" % role)
        return None
    spawnid = uuid.uuid4().hex[:8]
    log = os.path.join(root, "logs", "worker-%s-%s.log" % (role, spawnid))
    os.makedirs(os.path.dirname(log), exist_ok=True)
    kickoff = ("You are the %s. Claim your next task and complete it per your role "
               "instructions, then exit." % role)
    logf = open(log, "a")
    env = dict(os.environ, GRID_ROOT_OVERRIDE=root, GRID_SPAWNID=spawnid, GRID_ROLE=role)
    override = os.environ.get("GRID_SPAWN_CMD")
    if override:
        cmd = ["bash", "-c", override.format(log=shlex.quote(log), role=role)]
        proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, env=env)
    else:
        sysprompt = agent["body"]
        cmd = ["claude", "-p", kickoff, "--model", model,
               "--session-id", str(uuid.uuid4()),
               "--output-format", "stream-json", "--verbose",
               "--append-system-prompt", sysprompt, "--add-dir", root,
               "--dangerously-skip-permissions"]
        proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, cwd=root, env=env)
    workers = workers_state()
    workers.append({"spawnid": spawnid, "role": role, "pid": proc.pid,
                    "log": log, "bead": None, "started": time.time()})
    write_workers(workers)
    return {"spawnid": spawnid, "role": role, "pid": proc.pid, "log": log}
