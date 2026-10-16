import datetime
import json
import os
import shutil
import threading

from lightcycle.adapters.run_log import new_log_path, run_logged
from lightcycle.ports.lifecycle_runner import HookResult, LifecycleRunnerPort

_TAIL_CHARS = 2000
_STATE_FILE = "lifecycle-state.json"


def _tail(text):
    return text[-_TAIL_CHARS:]


class LifecycleRunnerAdapter(LifecycleRunnerPort):
    def __init__(self, config):
        self._config = config
        self._threads = {}
        self._results = {}
        self._lock = threading.Lock()

    def _execute(self, log_path, script_path, cwd, env, timeout, log_label):
        run = run_logged(
            self._config, log_label, log_path, script_path, cwd, env, None, timeout)
        output = _tail(run.stderr_tail + run.stdout)
        return HookResult(
            exit_code=run.exit_code, output=output, timed_out=run.timed_out,
            log_path=run.log_path)

    def run(self, script_path, cwd, env, timeout, log_label):
        log_path = new_log_path(self._config, log_label)
        return self._execute(log_path, script_path, cwd, env, timeout, log_label)

    def _body(self, key, args):
        result = self._execute(*args)
        with self._lock:
            self._results[key] = result

    def start(self, key, script_path, cwd, env, timeout, log_label):
        with self._lock:
            if key in self._threads:
                raise ValueError("lifecycle process %r is already running" % key)
            log_path = new_log_path(self._config, log_label)
            args = (log_path, script_path, cwd, env, timeout, log_label)
            thread = threading.Thread(target=self._body, args=(key, args), daemon=True)
            self._threads[key] = thread
        thread.start()
        return log_path

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

    def _under_data_root(self, path):
        root = os.path.realpath(self._config.workflow_data_root())
        target = os.path.realpath(path)
        if target == root or not target.startswith(root + os.sep):
            raise ValueError("%s is not under %s" % (path, root))
        return target

    def remove_data_dir(self, path):
        shutil.rmtree(self._under_data_root(path), ignore_errors=True)

    def remove_empty_dir(self, path):
        try:
            os.rmdir(self._under_data_root(path))
        except OSError:
            pass
