import os
import shlex
import subprocess
import sys
import time
import uuid

from lightcycle.adapters import fsio
from lightcycle.adapters.workers import process_start_time, register_worker
from lightcycle.adapters.workflow_source import default_bundle_root
from lightcycle.ports.spawner import SpawnerPort


def capture_pid_started(proc, get_start=process_start_time, sleep=time.sleep, attempts=5, interval=0.05):
    started = get_start(proc.pid)
    tries = 1
    while started is None and tries < attempts and proc.poll() is None:
        sleep(interval)
        started = get_start(proc.pid)
        tries += 1
    return started


def spawn_worker(config, role):
    root = config.data_root()
    bundle = default_bundle_root(config)
    agent = fsio.parse_step([bundle], role) if bundle else None
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
    env = dict(config.base_env(), LC_HOME=root,
               LC_SPAWNID=spawnid, LC_ROLE=role, LC_WORKER="1")
    pkg_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env["PYTHONPATH"] = os.pathsep.join(p for p in (pkg_parent, env.get("PYTHONPATH", "")) if p)
    override = config.spawn_cmd()
    if override:
        cmd = ["bash", "-c", override.format(log=shlex.quote(log), role=role)]
        proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, env=env)
    else:
        cmd = [sys.executable, "-m", "lightcycle.adapters.worker_session"]
        proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, cwd=root, env=env)
    pid_started = capture_pid_started(proc)
    if pid_started is None and proc.poll() is not None:
        return None
    register_worker(
        root,
        {
            "spawnid": spawnid,
            "role": role,
            "pid": proc.pid,
            "pid_started": pid_started,
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
