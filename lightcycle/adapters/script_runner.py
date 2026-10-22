import json
import os
import threading
from urllib.parse import quote, unquote

from lightcycle.adapters.run_log import new_log_path, run_logged
from lightcycle.adapters.workers import process_start_time, worker_alive
from lightcycle.ports.script_runner import ScriptResult, ScriptRunnerPort

_RECORDS_DIR = "script-runs"


class ScriptRunnerAdapter(ScriptRunnerPort):
    def __init__(self, config, groups):
        self._config = config
        self._groups = groups
        self._threads = {}
        self._results = {}
        self._lock = threading.Lock()

    def _records_dir(self):
        return os.path.join(self._config.data_root(), _RECORDS_DIR)

    def _record_path(self, key):
        return os.path.join(self._records_dir(), quote(key, safe="") + ".json")

    def _write_record(self, key, proc):
        os.makedirs(self._records_dir(), exist_ok=True)
        path = self._record_path(key)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w") as f:
            json.dump({"pid": proc.pid, "started": process_start_time(proc.pid)}, f)
        os.replace(tmp, path)

    def _remove_record(self, key):
        try:
            os.remove(self._record_path(key))
        except OSError:
            pass

    def _execute(self, log_path, script_path, cwd, env, stdin_text, timeout, log_label,
                 on_spawn=None):
        run = run_logged(
            self._config, log_label, log_path, script_path, cwd, env,
            stdin_text.encode("utf-8"), timeout, self._groups, on_spawn)
        return ScriptResult(
            exit_code=run.exit_code, stdout=run.stdout, stderr_tail=run.stderr_tail,
            timed_out=run.timed_out, log_path=run.log_path)

    def run(self, script_path, cwd, env, stdin_text, timeout, log_label):
        log_path = new_log_path(self._config, log_label)
        return self._execute(log_path, script_path, cwd, env, stdin_text, timeout, log_label)

    def _body(self, key, args):
        try:
            result = self._execute(*args, on_spawn=lambda proc: self._write_record(key, proc))
        finally:
            self._remove_record(key)
        with self._lock:
            self._results[key] = result

    def start(self, key, script_path, cwd, env, stdin_text, timeout, log_label):
        with self._lock:
            if key in self._threads:
                raise ValueError("script process %r is already running" % key)
            log_path = new_log_path(self._config, log_label)
            args = (log_path, script_path, cwd, env, stdin_text, timeout, log_label)
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

    def _read_record(self, path):
        try:
            with open(path) as f:
                data = json.load(f)
            return int(data["pid"]), data.get("started")
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def orphaned(self):
        try:
            names = sorted(os.listdir(self._records_dir()))
        except OSError:
            return []
        with self._lock:
            ours = set(self._threads)
        found = []
        for name in names:
            if not name.endswith(".json"):
                continue
            key = unquote(name[:-len(".json")])
            if key in ours:
                continue
            path = os.path.join(self._records_dir(), name)
            record = self._read_record(path)
            if record is not None and worker_alive(*record):
                found.append(key)
                continue
            try:
                os.remove(path)
            except OSError:
                pass
        return found
