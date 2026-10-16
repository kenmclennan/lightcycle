import threading

from lightcycle.adapters.run_log import new_log_path, run_logged
from lightcycle.ports.script_runner import ScriptResult, ScriptRunnerPort


class ScriptRunnerAdapter(ScriptRunnerPort):
    def __init__(self, config):
        self._config = config
        self._threads = {}
        self._results = {}
        self._lock = threading.Lock()

    def _execute(self, log_path, script_path, cwd, env, stdin_text, timeout, log_label):
        run = run_logged(
            self._config, log_label, log_path, script_path, cwd, env,
            stdin_text.encode("utf-8"), timeout)
        return ScriptResult(
            exit_code=run.exit_code, stdout=run.stdout, stderr_tail=run.stderr_tail,
            timed_out=run.timed_out, log_path=run.log_path)

    def run(self, script_path, cwd, env, stdin_text, timeout, log_label):
        log_path = new_log_path(self._config, log_label)
        return self._execute(log_path, script_path, cwd, env, stdin_text, timeout, log_label)

    def _body(self, key, args):
        result = self._execute(*args)
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
