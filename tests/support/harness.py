import io
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import the_grid.cli as cli
from the_grid.container import Container
from tests.support.fake_store import FakeStore

_AGENTS = {
    "coder": ("sonnet", "build", {"done": "review"}),
    "reviewer": ("opus", "review", {"done": "open-pr", "rejected": "build"}),
    "pr-watcher": ("sonnet", "open-pr", {"done": "ready-merge", "ci-failed": "build"}),
}


def _write_steps(root, roles):
    adir = Path(root) / "steps"
    adir.mkdir(exist_ok=True)
    for r in roles:
        model, step, routes = _AGENTS[r]
        fm = ["---", "model: %s" % model, "step: %s" % step, "routes:"]
        fm += ["  %s: %s" % (o, n) for o, n in routes.items()]
        fm += ["---", "# %s" % r, "stub"]
        (adir / ("%s.md" % r)).write_text("\n".join(fm) + "\n")


def _write_config(root):
    p = os.path.join(tempfile.mkdtemp(), "config")
    Path(p).write_text("projects: %s\nspecs: %s\n" % (root, root))
    return p


class Harness:
    def __init__(self, roles):
        self.root = tempfile.mkdtemp()
        os.environ["GRID_ROOT_OVERRIDE"] = self.root
        os.environ["GRID_CONFIG"] = _write_config(self.root)
        _write_steps(self.root, roles)
        self.store = FakeStore()
        cli.set_container(Container(store=self.store))

    def run(self, verb, *args):
        fn = getattr(cli, "cmd_" + verb.replace("-", "_"))
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                rc = fn([str(a) for a in args]) or 0
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
        return rc, out.getvalue(), err.getvalue()

    def ready_tasks(self, role):
        return [t for t in self.store.all_tasks() if t.status == "ready" and t.role == role]
