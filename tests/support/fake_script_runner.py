import dataclasses

from lightcycle.ports.script_runner import ScriptResult, ScriptRunnerPort

OK_EMPTY = ScriptResult(exit_code=0, stdout="")


class FakeScriptRunner(ScriptRunnerPort):
    def __init__(self, clock=None):
        self._clock = clock
        self._due = {}
        self.calls = []
        self.started = []
        self._programmed = {}
        self._run_programmed = {}
        self._running = {}
        self._finished = {}
        self._log_paths = {}
        self._orphans = {}
        self._started_at = {}

    def program(self, key, result):
        self._programmed[key] = result

    def program_run(self, script_path, result):
        self._run_programmed[script_path] = result

    def finish(self, key, result=None):
        self._finished[key] = result if result is not None else self._programmed[key]

    def finish_after(self, key, seconds, result=None):
        if self._clock is None:
            raise ValueError("finish_after needs a clock")
        self._due[key] = (self._clock() + seconds, result)

    def kill(self, key, signal=15):
        self._due.pop(key, None)
        self._finished[key] = ScriptResult(exit_code=-signal)

    def orphan_running(self):
        for key in list(self._running):
            self._orphans[key] = 0
            del self._running[key]
            self._finished.pop(key, None)
            self._due.pop(key, None)

    def run(self, script_path, cwd, env, stdin_text, timeout, log_label):
        self.calls.append({
            "script": script_path, "cwd": cwd, "env": dict(env), "stdin": stdin_text,
            "timeout": timeout, "log_label": log_label})
        return self._run_programmed.get(script_path, OK_EMPTY)

    def start(self, key, script_path, cwd, env, stdin_text, timeout, log_label):
        if key in self._running or key in self._orphans:
            raise ValueError("script process %r is already running" % key)
        call = {
            "key": key, "script": script_path, "cwd": cwd, "env": dict(env),
            "stdin": stdin_text, "timeout": timeout, "log_label": log_label}
        self.calls.append(call)
        self.started.append(call)
        self._running[key] = call
        self._started_at[key] = self._clock() if self._clock is not None else None
        self._log_paths[key] = "%s.log" % log_label
        return self._log_paths[key]

    def poll(self, key):
        if key not in self._running:
            raise KeyError(key)
        if key in self._due and self._clock() >= self._due[key][0]:
            self.finish(key, self._due.pop(key)[1])
        if key not in self._finished:
            return None
        del self._running[key]
        result = self._finished.pop(key)
        if result.log_path is None:
            result = dataclasses.replace(result, log_path=self._log_paths[key])
        started_at = self._started_at.pop(key, None)
        if self._clock is not None and result.started_at is None and result.finished_at is None:
            result = dataclasses.replace(
                result, started_at=started_at, finished_at=self._clock())
        return result

    def running(self):
        return sorted(self._running)

    def abandon(self, key):
        known = key in self._running
        self._running.pop(key, None)
        self._finished.pop(key, None)
        self._due.pop(key, None)
        return known

    def plant_orphan(self, key, pid):
        self._orphans[key] = pid

    def kill_orphan(self, key):
        self._orphans.pop(key, None)

    def orphaned(self):
        return sorted(k for k in self._orphans if k not in self._running)
