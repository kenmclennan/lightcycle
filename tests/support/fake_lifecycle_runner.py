import os

from lightcycle.ports.lifecycle_runner import HookResult, LifecycleRunnerPort

OK = HookResult(exit_code=0, output="")


class FakeLifecycleRunner(LifecycleRunnerPort):
    def __init__(self, due=None, dirs=None):
        self.calls = []
        self.started = []
        self.due = due if due is not None else {}
        self.dirs = set(dirs or ())
        self._programmed = {}
        self._running = {}
        self._finished = {}

    def program(self, hook, result, workflow=None):
        self._programmed[(hook, workflow)] = result

    def _result_for(self, env):
        hook = env.get("LC_WORKFLOW_HOOK")
        name = "%s/%s" % (env.get("LC_WORKFLOW_ORIGIN"), env.get("LC_WORKFLOW_NAME"))
        return self._programmed.get(
            (hook, name), self._programmed.get((hook, None), OK))

    def run(self, script_path, cwd, env, timeout):
        self.calls.append(
            {"script": script_path, "cwd": cwd, "env": dict(env), "timeout": timeout})
        return self._result_for(env)

    def start(self, key, script_path, cwd, env, timeout):
        if key in self._running:
            raise ValueError("lifecycle process %r is already running" % key)
        call = {"script": script_path, "cwd": cwd, "env": dict(env), "timeout": timeout}
        self.started.append((key, call))
        self._running[key] = call

    def finish(self, key, result):
        self._finished[key] = result

    def poll(self, key):
        if key not in self._running:
            raise KeyError(key)
        if key not in self._finished:
            return None
        del self._running[key]
        return self._finished.pop(key)

    def running(self):
        return sorted(self._running)

    def last_due(self, key):
        return self.due.get(key)

    def record_due(self, key, due):
        self.due[key] = due

    def ensure_data_dir(self, path):
        self.dirs.add(path)

    def data_dir_exists(self, path):
        return path in self.dirs

    def list_data_dirs(self, path):
        return sorted(
            os.path.basename(d) for d in self.dirs if os.path.dirname(d) == path)

    def remove_data_dir(self, path):
        self.dirs = {d for d in self.dirs if d != path and not d.startswith(path + os.sep)}
