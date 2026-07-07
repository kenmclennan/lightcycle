import os
import shlex
import subprocess
import sys
import time
import uuid

from lightcycle.adapters import fsio
from lightcycle.adapters.workers import register_worker
from lightcycle.ports.spawner import SpawnerPort


def spawn_worker(config, role):
    root = config.data_root()
    agent = fsio.parse_step([config.data_root(), config.library_root()], role)
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
    logf = open(log, "a")
    env = dict(config.base_env(), LC_HOME=root, LC_LIBRARY=config.library_root(),
               LC_SPAWNID=spawnid, LC_ROLE=role)
    pkg_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env["PYTHONPATH"] = os.pathsep.join(p for p in (pkg_parent, env.get("PYTHONPATH", "")) if p)
    override = config.spawn_cmd()
    if override:
        cmd = ["bash", "-c", override.format(log=shlex.quote(log), role=role)]
        proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, env=env)
    else:
        cmd = [sys.executable, "-m", "lightcycle.adapters.worker_session"]
        proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, cwd=root, env=env)
    register_worker(
        root,
        {
            "spawnid": spawnid,
            "role": role,
            "pid": proc.pid,
            "log": log,
            "step": None,
            "started": time.time(),
        },
    )
    return {"spawnid": spawnid, "role": role, "pid": proc.pid, "log": log}


class SpawnerAdapter(SpawnerPort):
    def __init__(self, config):
        self._config = config

    def spawn_worker(self, role):
        return spawn_worker(self._config, role)
