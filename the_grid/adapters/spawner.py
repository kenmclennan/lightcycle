import os
import shlex
import subprocess
import sys
import time
import uuid

from the_grid.adapters import fsio
from the_grid.adapters.workers import workers_state, write_workers
from the_grid.ports.spawner import SpawnerPort


def spawn_worker(config, role):
    root = config.grid_root()
    agent = fsio.parse_step(root, role)
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
    kickoff = (
        "You are the %s. Claim your next task and complete it per your role "
        "instructions, then exit." % role
    )
    logf = open(log, "a")
    env = dict(config.base_env(), GRID_ROOT_OVERRIDE=root, GRID_SPAWNID=spawnid, GRID_ROLE=role)
    override = config.spawn_cmd()
    if override:
        cmd = ["bash", "-c", override.format(log=shlex.quote(log), role=role)]
        proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, env=env)
    else:
        sysprompt = agent["body"]
        cmd = [
            "claude",
            "-p",
            kickoff,
            "--model",
            model,
            "--session-id",
            str(uuid.uuid4()),
            "--output-format",
            "stream-json",
            "--verbose",
            "--append-system-prompt",
            sysprompt,
            "--add-dir",
            root,
            "--dangerously-skip-permissions",
        ]
        proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, cwd=root, env=env)
    workers = workers_state(root)
    workers.append(
        {
            "spawnid": spawnid,
            "role": role,
            "pid": proc.pid,
            "log": log,
            "task": None,
            "started": time.time(),
        }
    )
    write_workers(root, workers)
    return {"spawnid": spawnid, "role": role, "pid": proc.pid, "log": log}


class SpawnerAdapter(SpawnerPort):
    def __init__(self, config):
        self._config = config

    def spawn_worker(self, role):
        return spawn_worker(self._config, role)
