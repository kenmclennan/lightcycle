from lightcycle.ports.script_runner import ScriptResult, ScriptRunnerPort

OK_EMPTY = ScriptResult(exit_code=0, stdout="")


class FakeScriptRunner(ScriptRunnerPort):
    def __init__(self):
        self.calls = []
        self.started = []
        self._programmed = {}
        self._running = {}
        self._finished = {}

    def program(self, key, result):
        self._programmed[key] = result

    def finish(self, key, result=None):
        self._finished[key] = result if result is not None else self._programmed[key]

    def run(self, script_path, cwd, env, stdin_text, timeout):
        self.calls.append({
            "script": script_path, "cwd": cwd, "env": dict(env), "stdin": stdin_text,
            "timeout": timeout})
        return OK_EMPTY

    def start(self, key, script_path, cwd, env, stdin_text, timeout):
        if key in self._running:
            raise ValueError("script process %r is already running" % key)
        call = {
            "key": key, "script": script_path, "cwd": cwd, "env": dict(env),
            "stdin": stdin_text, "timeout": timeout}
        self.calls.append(call)
        self.started.append(call)
        self._running[key] = call

    def poll(self, key):
        if key not in self._running:
            raise KeyError(key)
        if key not in self._finished:
            return None
        del self._running[key]
        return self._finished.pop(key)

    def running(self):
        return sorted(self._running)
