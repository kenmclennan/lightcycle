import datetime
import json
import os
import shutil
import subprocess
import threading

from lightcycle.ports.lifecycle_runner import HookResult, LifecycleRunnerPort

_TAIL_CHARS = 2000
_STATE_FILE = "lifecycle-state.json"


def _tail(text):
    return text[-_TAIL_CHARS:]


def _decode(raw):
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


class LifecycleRunnerAdapter(LifecycleRunnerPort):
    def __init__(self, config):
        self._config = config
        self._threads = {}
        self._results = {}
        self._lock = threading.Lock()

    def run(self, script_path, cwd, env, timeout):
        try:
            completed = subprocess.run(
                [script_path], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            return HookResult(
                exit_code=None, output=_tail(_decode(e.stdout)), timed_out=True)
        except OSError as e:
            return HookResult(exit_code=None, output=str(e))
        return HookResult(
            exit_code=completed.returncode, output=_tail(_decode(completed.stdout)))

    def _body(self, key, script_path, cwd, env, timeout):
        result = self.run(script_path, cwd, env, timeout)
        with self._lock:
            self._results[key] = result

    def start(self, key, script_path, cwd, env, timeout):
        with self._lock:
            if key in self._threads:
                raise ValueError("lifecycle process %r is already running" % key)
            thread = threading.Thread(
                target=self._body, args=(key, script_path, cwd, env, timeout), daemon=True)
            self._threads[key] = thread
        thread.start()

    def poll(self, key):
        with self._lock:
            if key not in self._threads:
                raise KeyError(key)
            if key not in self._results:
                return None
            del self._threads[key]
            return self._results.pop(key)

    def running(self):
        with self._lock:
            return sorted(self._threads)

    def _state_path(self):
        return os.path.join(self._config.data_root(), _STATE_FILE)

    def _read_state(self):
        path = self._state_path()
        if not os.path.exists(path):
            return {}
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("%s must hold a JSON object" % path)
        return data

    def last_due(self, key):
        raw = self._read_state().get(key)
        if raw is None:
            return None
        return datetime.datetime.fromisoformat(raw)

    def record_due(self, key, due):
        state = self._read_state()
        state[key] = due.isoformat()
        path = self._state_path()
        tmp = "%s.%d.tmp" % (path, os.getpid())
        try:
            with open(tmp, "w") as f:
                json.dump(state, f, sort_keys=True)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def ensure_data_dir(self, path):
        os.makedirs(path, exist_ok=True)

    def data_dir_exists(self, path):
        return os.path.isdir(path)

    def list_data_dirs(self, path):
        if not os.path.isdir(path):
            return []
        return sorted(e.name for e in os.scandir(path) if e.is_dir())

    def remove_data_dir(self, path):
        root = os.path.realpath(self._config.workflow_data_root())
        target = os.path.realpath(path)
        if target == root or not target.startswith(root + os.sep):
            raise ValueError("%s is not under %s" % (path, root))
        shutil.rmtree(target, ignore_errors=True)
