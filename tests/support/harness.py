import io
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import lightcycle.cli as cli
from lightcycle.config import _SEED_KEYS
from tests.support.fake_fs import graph_text_from_metas
from tests.support.fake_store import FakeStore
from tests.support.isolation import inject_container, make_syncable_git_repo

_AGENTS = {
    "coder": ("sonnet", "build", {"done": "review"}),
    "reviewer": ("opus", "review", {"done": "open-pr", "rejected": "build"}),
    "pr-watcher": ("sonnet", "open-pr", {"done": "ready-merge", "ci-failed": "build"}),
    "handle-feedback": ("sonnet", "handle-feedback", {}),
}


_ORIGIN = "lightcycle"
_SHA = "testsha"
DEFAULT_WORKFLOW = "%s/spec-driven" % _ORIGIN


def _write_bundle(root, roles, extra_steps=None, workflow_text=None):
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
    for filename, text in (extra_steps or {}).items():
        (adir / ("%s.md" % filename)).write_text(text)
    wdir = bundle / "workflows"
    wdir.mkdir(parents=True)
    graph_text = (
        workflow_text if workflow_text is not None
        else graph_text_from_metas(metas, entry="build")
    )
    (wdir / "spec-driven.md").write_text(graph_text)
    (origin_dir / "origin.toml").write_text(
        'url = "local"\nref = "main"\ncurrent = "%s"\n' % _SHA)


def _write_config(root):
    p = os.path.join(tempfile.mkdtemp(), "config")
    seeded = dict(_SEED_KEYS)
    seeded["projects"] = root
    seeded["specs"] = root
    seeded["default-origin"] = "lightcycle"
    seeded["max-agents"] = "0"
    seeded["backups-dir"] = tempfile.mkdtemp()
    Path(p).write_text("".join("%s: %s\n" % (k, v) for k, v in seeded.items()))
    return p


class Harness:
    def __init__(self, roles, github=None, extra_steps=None, workflow_text=None):
        self.root = tempfile.mkdtemp()
        make_syncable_git_repo(self.root)
        Path(self.root, "store.db").touch()
        self._cfg = _write_config(self.root)
        _write_bundle(self.root, roles, extra_steps=extra_steps, workflow_text=workflow_text)
        self.store = FakeStore()
        self._github = github
        inject_container(
            self, store=self.store, home=self.root, config_path=self._cfg, github=github
        )

    def set_github(self, github):
        self._github = github
        inject_container(
            self, store=self.store, home=self.root, config_path=self._cfg, github=github
        )

    def run_as_worker(self, spawnid, verb, *args):
        inject_container(self, store=self.store, home=self.root, config_path=self._cfg,
                         extra_env={"LC_SPAWNID": spawnid}, github=self._github)
        try:
            return self.run(verb, *args)
        finally:
            inject_container(
                self, store=self.store, home=self.root, config_path=self._cfg,
                github=self._github,
            )

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
