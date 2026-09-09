import os
import shlex
import subprocess
import sys
import time
import uuid

from lightcycle.adapters.workers import process_start_time, register_worker, set_pid_started
from lightcycle.domain.work.worker_log import worker_log_filename
from lightcycle.ports.spawner import SpawnerPort
from lightcycle.ports.workers import RegistryUnreadable


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
    spawnid = uuid.uuid4().hex[:8]
    log = os.path.join(root, "logs", worker_log_filename(role, spawnid))
    os.makedirs(os.path.dirname(log), exist_ok=True)
    logf = open(log, "a")
    env = dict(config.base_env(), LC_HOME=root,
               LC_SPAWNID=spawnid, LC_ROLE=role, LC_WORKER="1")
    pkg_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env["PYTHONPATH"] = os.pathsep.join(p for p in (pkg_parent, env.get("PYTHONPATH", "")) if p)
    override = config.spawn_cmd()
    if override:
        cmd = ["bash", "-c", override.format(log=shlex.quote(log), role=role)]
        proc = subprocess.Popen(cmd, stdout=logf, stderr=logf, env=env, start_new_session=True)
    else:
        cmd = [sys.executable, "-m", "lightcycle.adapters.worker_session"]
        proc = subprocess.Popen(
            cmd, stdout=logf, stderr=logf, cwd=root, env=env, start_new_session=True
        )
    try:
        register_worker(
            root,
            {
                "spawnid": spawnid,
                "role": role,
                "pid": proc.pid,
                "pid_started": None,
                "log": log,
                "step": None,
                "started": time.time(),
            },
        )
    except RegistryUnreadable:
        try:
            proc.terminate()
        except OSError:
            pass
        logf.close()
        return None
    pid_started = capture_pid_started(proc)
    if pid_started is None and proc.poll() is not None:
        return None
    set_pid_started(root, spawnid, pid_started)
    return {"spawnid": spawnid, "role": role, "pid": proc.pid, "log": log}


def spawn_pool(config):
    root = config.data_root()
    log = os.path.join(root, "logs", "run.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    logf = open(log, "a")
    env = dict(config.base_env(), LC_HOME=root)
    pkg_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env["PYTHONPATH"] = os.pathsep.join(p for p in (pkg_parent, env.get("PYTHONPATH", "")) if p)
    proc = subprocess.Popen(
        [sys.executable, "-m", "lightcycle", "start"],
        stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
        cwd=root, env=env, start_new_session=True,
    )
    return proc.pid


class SpawnerAdapter(SpawnerPort):
    def __init__(self, config):
        self._config = config

    def spawn_worker(self, role):
        return spawn_worker(self._config, role)

    def spawn_pool(self):
        return spawn_pool(self._config)
