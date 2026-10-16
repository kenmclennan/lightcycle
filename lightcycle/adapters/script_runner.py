import subprocess
import threading

from lightcycle.ports.script_runner import ScriptResult, ScriptRunnerPort

_TAIL_CHARS = 2000


def _decode(raw):
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


class ScriptRunnerAdapter(ScriptRunnerPort):
    def __init__(self):
        self._threads = {}
        self._results = {}
        self._lock = threading.Lock()

    def run(self, script_path, cwd, env, stdin_text, timeout):
        try:
            completed = subprocess.run(
                [script_path], cwd=cwd, env=env, input=stdin_text.encode("utf-8"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            return ScriptResult(
                exit_code=None, stdout=_decode(e.stdout),
                stderr_tail=_decode(e.stderr)[-_TAIL_CHARS:], timed_out=True)
        except OSError as e:
            return ScriptResult(exit_code=None, stderr_tail=str(e)[-_TAIL_CHARS:])
        return ScriptResult(
            exit_code=completed.returncode, stdout=_decode(completed.stdout),
            stderr_tail=_decode(completed.stderr)[-_TAIL_CHARS:])

    def _body(self, key, script_path, cwd, env, stdin_text, timeout):
        result = self.run(script_path, cwd, env, stdin_text, timeout)
        with self._lock:
            self._results[key] = result

    def start(self, key, script_path, cwd, env, stdin_text, timeout):
        with self._lock:
            if key in self._threads:
                raise ValueError("script process %r is already running" % key)
            thread = threading.Thread(
                target=self._body, args=(key, script_path, cwd, env, stdin_text, timeout),
                daemon=True)
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
