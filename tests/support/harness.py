import io
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import lightcycle.cli as cli
from tests.support.fake_fs import graph_text_from_metas
from tests.support.fake_store import FakeStore
from tests.support.isolation import inject_container

_AGENTS = {
    "coder": ("sonnet", "build", {"done": "review"}),
    "reviewer": ("opus", "review", {"done": "open-pr", "rejected": "build"}),
    "pr-watcher": ("sonnet", "open-pr", {"done": "ready-merge", "ci-failed": "build"}),
}


_ORIGIN = "lightcycle"
_SHA = "testsha"
DEFAULT_WORKFLOW = "%s/spec-driven" % _ORIGIN


def _write_bundle(root, roles):
    origin_dir = Path(root) / "workflows" / _ORIGIN
    bundle = origin_dir / _SHA
    adir = bundle / "steps"
    adir.mkdir(parents=True)
    metas = {}
    for r in roles:
        model, step, routes = _AGENTS[r]
        fm = ["---", "model: %s" % model, "step: %s" % step, "routes:"]
        fm += ["  %s: %s" % (o, n) for o, n in routes.items()]
        fm += ["---", "# %s" % r, "stub"]
        (adir / ("%s.md" % r)).write_text("\n".join(fm) + "\n")
        metas[r] = {"model": model, "step": step, "routes": routes}
    wdir = bundle / "workflows"
    wdir.mkdir(parents=True)
    (wdir / "spec-driven.md").write_text(graph_text_from_metas(metas, entry="build"))
    (origin_dir / "origin.toml").write_text(
        'url = "local"\nref = "main"\ncurrent = "%s"\n' % _SHA)


def _write_config(root):
    p = os.path.join(tempfile.mkdtemp(), "config")
    Path(p).write_text(
        "projects: %s\nspecs: %s\ndefault-origin: lightcycle\n" % (root, root)
    )
    return p


class Harness:
    def __init__(self, roles):
        self.root = tempfile.mkdtemp()
        cfg = _write_config(self.root)
        _write_bundle(self.root, roles)
        self.store = FakeStore()
        inject_container(self, store=self.store, home=self.root, config_path=cfg)

    def run(self, verb, *args):
        fn = getattr(cli, "cmd_" + verb.replace("-", "_"))
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                rc = fn([str(a) for a in args]) or 0
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
        return rc, out.getvalue(), err.getvalue()

    def ready_steps(self, role):
        return [t for t in self.store.all_nodes() if t.state == "ready" and t.role == role]
