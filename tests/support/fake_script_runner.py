import dataclasses

from lightcycle.ports.script_runner import ScriptResult, ScriptRunnerPort

OK_EMPTY = ScriptResult(exit_code=0, stdout="")


class FakeScriptRunner(ScriptRunnerPort):
    def __init__(self):
        self.calls = []
        self.started = []
        self._programmed = {}
        self._running = {}
        self._finished = {}
        self._log_paths = {}

    def program(self, key, result):
        self._programmed[key] = result

    def finish(self, key, result=None):
        self._finished[key] = result if result is not None else self._programmed[key]

    def run(self, script_path, cwd, env, stdin_text, timeout, log_label):
        self.calls.append({
            "script": script_path, "cwd": cwd, "env": dict(env), "stdin": stdin_text,
            "timeout": timeout, "log_label": log_label})
        return OK_EMPTY

    def start(self, key, script_path, cwd, env, stdin_text, timeout, log_label):
        if key in self._running:
            raise ValueError("script process %r is already running" % key)
        call = {
            "key": key, "script": script_path, "cwd": cwd, "env": dict(env),
            "stdin": stdin_text, "timeout": timeout, "log_label": log_label}
        self.calls.append(call)
        self.started.append(call)
        self._running[key] = call
        self._log_paths[key] = "%s.log" % log_label
        return self._log_paths[key]

    def poll(self, key):
        if key not in self._running:
            raise KeyError(key)
        if key not in self._finished:
            return None
        del self._running[key]
        result = self._finished.pop(key)
        if result.log_path is None:
            result = dataclasses.replace(result, log_path=self._log_paths[key])
        return result

    def running(self):
        return sorted(self._running)
