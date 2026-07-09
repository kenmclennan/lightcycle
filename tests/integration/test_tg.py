import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TG = str(ROOT / "bin" / "lc")

sys.path.insert(0, str(ROOT))
import lightcycle.cli as _cli_mod
from tests.support.fake_fs import graph_text_from_metas
from tests.support.fake_store import FakeStore
from lightcycle.adapters.gitio import GitAdapter
from lightcycle.application.services.flow import FlowService
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.domain.work import Artifact

_ABSENT_CONFIG = os.path.join(tempfile.mkdtemp(), "absent-config")
os.environ["LC_CONFIG"] = _ABSENT_CONFIG


def run_tg(*args, root=None, config=None):
    env = dict(os.environ)
    if root:
        env["LC_ROOT_OVERRIDE"] = root
    else:
        env["LC_HOME"] = tempfile.mkdtemp()
    if config:
        env["LC_CONFIG"] = config
    return subprocess.run([sys.executable, TG, *args], capture_output=True, text=True, env=env)


def write_config(projects=None, specs=None):
    p = os.path.join(tempfile.mkdtemp(), "config")
    lines = []
    if projects is not None:
        lines.append("projects: %s" % projects)
    if specs is not None:
        lines.append("specs: %s" % specs)
    lines += [
        "shortcode: tg",
        "branch-prefix: feat",
        "default-workflow: standard",
        "max-agents: 5",
        "worktree-retries: 6",
        "worktree-retry-sleep: 0.25",
        "max-boot-seconds: 120",
        "poll-seconds: 5",
        "worker-history: 20",
        "editor: vi",
        "retro-interval-days: 7",
        "retro-min-items: 3",
    ]
    Path(p).write_text("".join(l + "\n" for l in lines))
    return p


def new_store():
    return tempfile.mkdtemp()


def git_in(root, *a):
    return subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, check=True)


def make_repo(parent, name):
    remote = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", "--bare", remote], check=True)
    d = os.path.join(parent, name)
    os.makedirs(d, exist_ok=True)
    subprocess.run(["git", "init", "-q", d], check=True)
    git_in(d, "config", "user.email", "t@t")
    git_in(d, "config", "user.name", "t")
    git_in(d, "checkout", "-q", "-b", "main")
    (Path(d) / "README").write_text("x")
    git_in(d, "add", ".")
    git_in(d, "commit", "-q", "-m", "init")
    git_in(d, "remote", "add", "origin", remote)
    git_in(d, "push", "-q", "origin", "main")
    git_in(d, "fetch", "-q", "origin")
    return d


def _reset_git_repo(repo):
    listing = git_in(repo, "worktree", "list", "--porcelain").stdout
    for block in listing.split("\n\n"):
        lines = block.splitlines()
        if not lines:
            continue
        path = lines[0].split(" ", 1)[1]
        if os.path.realpath(path) != os.path.realpath(repo):
            subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", path], check=True)
    subprocess.run(["git", "-C", repo, "worktree", "prune"], check=True)
    git_in(repo, "checkout", "-q", "main")
    for b in git_in(repo, "branch", "--format=%(refname:short)").stdout.split():
        if b != "main":
            git_in(repo, "branch", "-D", b)


_AGENT_SPECS = {
    "coder": ("sonnet", "build", {"done": "review"}),
    "reviewer": ("opus", "review", {"done": "open-pr", "rejected": "build"}),
    "pr-watcher": ("sonnet", "open-pr", {"done": "ready-merge", "ci-failed": "build"}),
    "driver": ("opus", None, None),
}

_STEP_SIGNALS = {"review": {"review_rounds": "rejected"}, "open-pr": {"conflicts": "~conflict"}}


def write_workflow(root, metas, name="standard", entry=None):
    wdir = Path(root) / "workflows"
    wdir.mkdir(exist_ok=True)
    (wdir / ("%s.md" % name)).write_text(graph_text_from_metas(metas, entry=entry))


def write_workflow_from_steps(root, name="standard"):
    from lightcycle.adapters import frontmatter

    metas = {}
    for f in sorted((Path(root) / "steps").glob("*.md")):
        meta, _ = frontmatter.split_frontmatter(f.read_text())
        metas[f.stem] = meta
    write_workflow(root, metas, name)


def write_steps(root, roles=("coder", "reviewer", "pr-watcher", "driver")):
    adir = Path(root) / "steps"
    adir.mkdir(exist_ok=True)
    metas = {}
    for r in roles:
        model, step, routes = _AGENT_SPECS[r]
        fm = ["---", "model: %s" % model]
        meta = {"model": model}
        if step:
            fm.append("step: %s" % step)
            meta["step"] = step
        if routes:
            fm.append("routes:")
            fm += ["  %s: %s" % (o, n) for o, n in routes.items()]
            meta["routes"] = routes
        if _STEP_SIGNALS.get(step):
            fm.append("signals:")
            fm += ["  %s: %s" % (k, v) for k, v in _STEP_SIGNALS[step].items()]
            meta["signals"] = _STEP_SIGNALS[step]
        fm += ["---", "# %s" % r, "stub"]
        (adir / ("%s.md" % r)).write_text("\n".join(fm) + "\n")
        metas[r] = meta
    write_workflow(root, metas, entry="build")


_CONTRACT_SPECS = {
    "coder": dict(
        model="sonnet",
        step="build",
        accepts={"spec": "required", "branch": "optional"},
        produces={"branch": "required"},
        routes={"done": "review"},
    ),
    "reviewer": dict(
        model="opus",
        step="review",
        accepts={"spec": "required", "branch": "required"},
        produces={},
        routes={"done": "open-pr", "rejected": "build"},
    ),
    "pr-watcher": dict(
        model="sonnet",
        step="open-pr",
        accepts={"branch": "required"},
        produces={"pr": "required"},
        routes={"done": "ready-merge", "ci-failed": "build"},
    ),
}


def write_contract_steps(root, specs=None):
    specs = specs or _CONTRACT_SPECS
    adir = Path(root) / "steps"
    adir.mkdir(exist_ok=True)
    for r, s in specs.items():
        fm = ["---", "model: %s" % s["model"], "step: %s" % s["step"]]
        for blk in ("accepts", "produces", "routes"):
            d = s.get(blk) or {}
            if d:
                fm.append("%s:" % blk)
                fm += ["  %s: %s" % (k, v) for k, v in d.items()]
        fm += ["---", "# %s" % r, "stub"]
        (adir / ("%s.md" % r)).write_text("\n".join(fm) + "\n")
    write_workflow(root, specs, entry="build")


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


def _file_compat(argv):
    args = list(argv)
    spec = args[0]
    opts = {}
    blocked = []
    i = 1
    while i < len(args):
        k, v = args[i][2:], args[i + 1]
        if k == "blocked-by":
            blocked.append(v)
        else:
            opts[k] = v
        i += 2
    title = os.path.splitext(os.path.basename(spec))[0]
    nargs = ["item", title]
    for k, flag in (("theme", "--parent"), ("project", "--project"),
                    ("goal", "--goal"), ("workflow", "--workflow")):
        if opts.get(k):
            nargs += [flag, opts[k]]
    rc, item, err = call(_cli_mod.cmd_new, *nargs)
    item = item.strip()
    if rc:
        sys.stderr.write(err)
        return rc
    call(_cli_mod.cmd_attach, item, "spec", spec)
    if opts.get("repo"):
        call(_cli_mod.cmd_attach, item, "repo", opts["repo"])
    sargs = [item, "--state", "active"]
    if opts.get("workflow"):
        sargs += ["--workflow", opts["workflow"]]
    if opts.get("step"):
        sargs += ["--step", opts["step"]]
    rc, step_id, err = call(_cli_mod.cmd_set, *sargs)
    if rc:
        sys.stderr.write(err)
        return rc
    for b in blocked:
        call(_cli_mod.cmd_dep, step_id.strip(), "--needs", b)
    print(item)
    return 0


def _fake_setUp(test, *, steps=False, contract_steps=False):
    test.root = tempfile.mkdtemp()
    os.environ["LC_ROOT_OVERRIDE"] = test.root
    os.environ["LC_CONFIG"] = write_config(projects=test.root, specs=test.root)
    write_workflow(test.root, {})
    if steps:
        write_steps(test.root)
    if contract_steps:
        write_contract_steps(test.root)
    test.store = FakeStore()
    test._orig = _cli_mod._container
    _cli_mod.set_container(_cli_mod.Container(store=test.store))
    test.addCleanup(lambda: _cli_mod.set_container(test._orig))
    test.addCleanup(lambda: os.environ.pop("LC_ROOT_OVERRIDE", None))
    test.addCleanup(lambda: os.environ.__setitem__("LC_CONFIG", _ABSENT_CONFIG))


class TestSkeleton(unittest.TestCase):
    def test_help_lists_subcommands(self):
        r = run_tg("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for verb in ("status", "claim", "done", "start", "sweep"):
            self.assertIn(verb, r.stdout)

    def test_unknown_subcommand_exits_2(self):
        r = run_tg("wibble")
        self.assertEqual(r.returncode, 2)

    def test_help_is_grouped_and_described(self):
        r = run_tg("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("See what's happening", r.stdout)
        self.assertIn("Start working", r.stdout)
        for line in r.stdout.splitlines():
            if line.strip().startswith("status "):
                self.assertGreater(len(line.split()), 3)
                break
        else:
            self.fail("status command not listed with a description")


class TestSpecsDir(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_specs_dir_prints_specs_root_from_config(self):
        rc, out, err = call(_cli_mod.cmd_specs_dir)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), self.root)


class TestModel(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_task_mapping_and_status(self):
        bid = self.store.create_step("build: thing", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_show, bid)
        self.assertEqual(rc, 0, err)
        t = json.loads(out)
        self.assertEqual(t["role"], "coder")
        self.assertEqual(t["step"], "build")
        self.assertEqual(t["type"], "step")
        self.assertEqual(t["state"], "ready")

    def test_status_lanes_json(self):
        h = self.store.create_step("spec: x", step="spec", role="human")
        c = self.store.create_step("build: y", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_status, "--json")
        self.assertEqual(rc, 0, err)
        s = json.loads(out)
        self.assertIn(h, [t["id"] for t in s["inbox"]])
        self.assertIn(c, [t["id"] for t in s["queue"]])


class TestClaim(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_claim_returns_and_marks_in_progress(self):
        c = self.store.create_step("build: y", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(rc, 0, err)
        t = json.loads(out)
        self.assertEqual(t["id"], c)
        self.assertEqual(t["state"], "in_progress")
        rc2, out2, _ = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(out2.strip(), "")

    def test_claim_ignores_human(self):
        self.store.create_step("spec: x", step="spec", role="human")
        rc, out, _ = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(out.strip(), "")

    def test_claim_assigns_worker_spawnid(self):
        b = self.store.create_step("build: y", step="build", role="coder")
        old = os.environ.get("LC_SPAWNID")
        os.environ["LC_SPAWNID"] = "spawn-xyz"
        try:
            call(_cli_mod.cmd_claim, "coder")
        finally:
            if old is None:
                os.environ.pop("LC_SPAWNID", None)
            else:
                os.environ["LC_SPAWNID"] = old
        self.assertEqual(self.store.get_node(b).claimed_by, "spawn-xyz")


class TestFlow(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_advance_creates_next_step(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        self.store.close(b, "done")
        rc, out, err = call(_cli_mod.cmd_advance, b, "done")
        self.assertEqual(rc, 0, err)
        new = out.strip()
        self.assertTrue(new)
        rc2, out2, _ = call(_cli_mod.cmd_show, new)
        nt = json.loads(out2)
        self.assertEqual(nt["role"], "reviewer")
        self.assertEqual(nt["step"], "review")

    def test_ready_roles(self):
        self.store.create_step("build: t", step="build", role="coder")
        rc, out, _ = call(_cli_mod.cmd_ready_roles)
        self.assertIn("coder", out.split())


class TestDoneBlock(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_done_closes_and_advances(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "done")
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.strip())
        self.assertEqual(self.store.get_node(b).state, "done")

    def test_done_unknown_outcome_errors_without_closing(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "banana")
        self.assertEqual(rc, 1)
        self.assertEqual(self.store.get_node(b).state, "ready")

    def test_block_writes_metadata_and_routes_human(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_set, b, "--state", "blocked", "--branch", "grid/x", "--needs", "confirm aud")
        self.assertEqual(rc, 0, err)
        step = self.store.get_node(b)
        self.assertEqual(step.needs, "confirm aud")
        self.assertEqual(step.role, "human")
        self.assertEqual(self.store._records[b]["metadata"]["branch"], "grid/x")

    def test_block_clears_assignee_and_surfaces_in_inbox(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        self.store.claim_ready("coder")
        rc, out, err = call(_cli_mod.cmd_set, b, "--state", "blocked", "--needs", "rebase first")
        self.assertEqual(rc, 0, err)
        self.assertIsNone(self.store.get_node(b).claimed_by)
        rc2, inbox_out, _ = call(_cli_mod.cmd_inbox)
        self.assertIn(b, inbox_out)

    def test_done_note_forwards_to_next_task(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "done", "--note", "fix the coverage")
        self.assertEqual(rc, 0, err)
        new = out.strip()
        self.assertTrue(new)
        notes = self.store.get_node(new).notes or ""
        self.assertIn("from build (done):", notes)
        self.assertIn("fix the coverage", notes)
        rc2, shown_out, _ = call(_cli_mod.cmd_show, new)
        shown = json.loads(shown_out)
        self.assertIn("fix the coverage", shown.get("notes") or "")

    def test_done_without_note_unchanged(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "done")
        self.assertEqual(rc, 0, err)
        new = out.strip()
        self.assertTrue(new)
        self.assertNotIn("from build", self.store.get_node(new).notes or "")

    def test_done_note_accepts_unquoted_multiword(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "done", "--note", "fix", "the", "flaky", "test")
        self.assertEqual(rc, 0, err)
        notes = self.store.get_node(out.strip()).notes or ""
        self.assertIn("fix the flaky test", notes)


class TestSweep(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)
        (Path(self.root) / "logs").mkdir(exist_ok=True)

    def test_sweep_releases_orphaned_claim(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        self.store.claim_ready("coder")
        rc, out, err = call(_cli_mod.cmd_sweep)
        self.assertEqual(rc, 0, err)
        step = self.store.get_node(b)
        self.assertEqual(step.state, "ready")
        self.assertIsNone(step.claimed_by)


class TestWorkersAdapterEffects(unittest.TestCase):
    def test_pid_alive_and_kill_hit_a_real_process_never_the_test(self):
        from lightcycle.adapters import workers as workers_adapter

        alive = subprocess.Popen(["sleep", "300"])
        self.addCleanup(lambda: alive.poll() is None and alive.kill())
        done = subprocess.Popen(["true"])
        done.wait()

        self.assertTrue(workers_adapter.pid_alive(alive.pid))
        self.assertFalse(workers_adapter.pid_alive(done.pid))

        workers_adapter.kill(alive.pid)
        alive.wait(timeout=5)
        self.assertIsNotNone(alive.poll())


class TestSpawn(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        for d in ("steps", "logs"):
            (Path(self.root) / d).mkdir(exist_ok=True)
        for r in ("coder", "reviewer", "pr-watcher"):
            (Path(self.root) / "steps" / ("%s.md" % r)).write_text(
                "---\nmodel: sonnet\n---\nstub %s" % r
            )

    def test_spawn_records_worker_log_and_lists_in_ps(self):
        env = dict(os.environ, LC_ROOT_OVERRIDE=self.root, LC_SPAWN_CMD="echo started >> {log}")
        r = subprocess.run(
            [sys.executable, TG, "spawn", "coder"], capture_output=True, text=True, env=env
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0]["role"], "coder")
        self.assertTrue(os.path.exists(workers[0]["log"]))
        r = subprocess.run(
            [sys.executable, TG, "ps", "--all", "--json"], capture_output=True, text=True, env=env
        )
        self.assertEqual(json.loads(r.stdout)[0]["role"], "coder")


class TestPs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = new_store()
        (Path(cls.root) / "logs").mkdir(exist_ok=True)

    def _write_workers(self, workers):
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(workers))

    def _run_ps(self, *args):
        env = dict(os.environ, LC_ROOT_OVERRIDE=self.root)
        return subprocess.run(
            [sys.executable, TG, "ps", *args, "--json"], capture_output=True, text=True, env=env
        )

    def test_default_shows_only_alive_workers(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        self._write_workers(
            [
                {"spawnid": "A", "role": "coder", "pid": os.getpid(), "log": "x", "step": "t1"},
                {"spawnid": "B", "role": "reviewer", "pid": dead.pid, "log": "y", "step": "t2"},
            ]
        )
        r = self._run_ps()
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role"], "coder")

    def test_all_shows_alive_and_dead_workers(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        self._write_workers(
            [
                {"spawnid": "A", "role": "coder", "pid": os.getpid(), "log": "x", "step": "t1"},
                {"spawnid": "B", "role": "reviewer", "pid": dead.pid, "log": "y", "step": "t2"},
            ]
        )
        r = self._run_ps("--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertEqual(len(rows), 2)
        self.assertEqual({w["role"] for w in rows}, {"coder", "reviewer"})


class TestRun(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for d in ("steps", "logs", "flows"):
            (Path(self.root) / d).mkdir(exist_ok=True)
        (Path(self.root) / "store.db").touch()
        for r in ("coder", "reviewer", "pr-watcher"):
            (Path(self.root) / "steps" / ("%s.md" % r)).write_text(
                "---\nmodel: sonnet\n---\nstub %s" % r
            )
        write_workflow_from_steps(self.root)
        os.environ["LC_ROOT_OVERRIDE"] = self.root
        os.environ["LC_SPAWN_CMD"] = "echo x >> {log}"
        os.environ["LC_CONFIG"] = write_config(projects=self.root, specs=self.root)
        self.store = FakeStore()
        self._orig = _cli_mod._container
        _cli_mod.set_container(_cli_mod.Container(store=self.store))
        self.addCleanup(lambda: _cli_mod.set_container(self._orig))
        self.addCleanup(lambda: os.environ.pop("LC_ROOT_OVERRIDE", None))
        self.addCleanup(lambda: os.environ.pop("LC_SPAWN_CMD", None))
        self.addCleanup(lambda: os.environ.__setitem__("LC_CONFIG", _ABSENT_CONFIG))

    def _run_once(self):
        return call(_cli_mod.cmd_start, "--once")

    def _workers(self):
        return json.loads((Path(self.root) / "logs" / "workers.json").read_text())

    def _preset_worker(self, **w):
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps([w]))

    def test_run_once_spawns_for_ready_role(self):
        self.store.create_step("build: t", step="build", role="coder")
        rc, _, err = self._run_once()
        self.assertEqual(rc, 0, err)
        self.assertTrue(any(w["role"] == "coder" for w in self._workers()))

    def test_queue_lists_ready(self):
        c = self.store.create_step("build: y", step="build", role="coder")
        rc, out, _ = call(_cli_mod.cmd_queue, "5")
        self.assertIn(c, out)

    def test_run_skips_role_with_inflight_worker(self):
        self.store.create_step("build: t", step="build", role="coder")
        self._preset_worker(
            spawnid="boot", role="coder", pid=os.getpid(), log="x", step=None, started=time.time()
        )
        rc, _, err = self._run_once()
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self._workers()), 1)

    def test_run_pool_fills_up_to_max_agents(self):
        for i in range(7):
            self.store.create_step("build: %d" % i, step="build", role="coder")
        for i in range(3):
            self.store.create_step("review: %d" % i, step="review", role="reviewer")
        rc, _, err = self._run_once()
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self._workers()), 5)

    def test_run_pool_respects_max_agents_env(self):
        for i in range(5):
            self.store.create_step("build: %d" % i, step="build", role="coder")
        os.environ["LC_MAX_AGENTS"] = "2"
        self.addCleanup(lambda: os.environ.pop("LC_MAX_AGENTS", None))
        rc, _, err = self._run_once()
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self._workers()), 2)

    def _breaker_state(self):
        return json.loads((Path(self.root) / "logs" / "breaker.json").read_text())

    def test_run_opens_breaker_on_a_rejected_rate_limit_event_and_stops_spawning(self):
        self.store.create_step("build: t", step="build", role="coder")
        log_path = Path(self.root) / "logs" / "worker-coder-dead.log"
        log_path.write_text(
            '{"type":"rate_limit_event","rate_limit_info":'
            '{"status":"rejected","resetsAt":9999999999}}\n'
        )
        dead = subprocess.Popen(["true"])
        dead.wait()
        self._preset_worker(
            spawnid="dead", role="coder", pid=dead.pid, log=str(log_path), step=None, started=0
        )
        rc, _, err = self._run_once()
        self.assertEqual(rc, 0, err)
        self.assertEqual(self._breaker_state(), {"open": True, "reset_at": 9999999999})
        self.assertEqual(len(self._workers()), 1)

    def test_run_spawns_nothing_while_breaker_open_pre_reset(self):
        self.store.create_step("build: t", step="build", role="coder")
        (Path(self.root) / "logs" / "workers.json").write_text("[]")
        (Path(self.root) / "logs" / "breaker.json").write_text(
            json.dumps({"open": True, "reset_at": time.time() + 9999})
        )
        rc, _, err = self._run_once()
        self.assertEqual(rc, 0, err)
        self.assertEqual(self._workers(), [])

    def test_run_loop_first_tick_does_not_replay_old_hook_completions(self):
        (Path(self.root) / "steps" / "auditor.md").write_text(
            "---\nmodel: sonnet\nstep: audit\non_theme_close: true\n---\nstub auditor"
        )
        tid = self.store.create_step("audit: theme", step="audit", role="auditor")
        self.store.close(tid, "done")
        self.store._records[tid]["closed_at"] = "2020-01-01T00:00:00"
        with patch("time.sleep", side_effect=KeyboardInterrupt):
            rc, out, err = call(_cli_mod.cmd_start)
        self.assertEqual(rc, 0, err)
        self.assertNotIn(tid, out)


class TestRunSingletonLock(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for d in ("steps", "logs", "flows"):
            (Path(self.root) / d).mkdir(exist_ok=True)
        (Path(self.root) / "store.db").touch()
        for r in ("coder", "reviewer", "pr-watcher"):
            (Path(self.root) / "steps" / ("%s.md" % r)).write_text(
                "---\nmodel: sonnet\n---\nstub %s" % r
            )
        write_workflow_from_steps(self.root)
        os.environ["LC_ROOT_OVERRIDE"] = self.root
        os.environ["LC_SPAWN_CMD"] = "echo x >> {log}"
        os.environ["LC_CONFIG"] = write_config(projects=self.root, specs=self.root)
        self.store = FakeStore()
        self._orig = _cli_mod._container
        _cli_mod.set_container(_cli_mod.Container(store=self.store))
        self.addCleanup(lambda: _cli_mod.set_container(self._orig))
        self.addCleanup(lambda: os.environ.pop("LC_ROOT_OVERRIDE", None))
        self.addCleanup(lambda: os.environ.pop("LC_SPAWN_CMD", None))
        self.addCleanup(lambda: os.environ.__setitem__("LC_CONFIG", _ABSENT_CONFIG))

    def _run_once(self):
        return call(_cli_mod.cmd_start, "--once")

    def _lock_path(self):
        return Path(self.root) / ".lc-run.pid"

    def test_second_start_refused_while_holder_alive(self):
        self._lock_path().write_text(str(os.getpid()))
        rc, _, err = self._run_once()
        self.assertNotEqual(rc, 0)
        self.assertIn("already running, pid %d" % os.getpid(), err)

    def test_start_succeeds_after_holder_releases(self):
        rc1, _, err1 = self._run_once()
        self.assertEqual(rc1, 0, err1)
        self.assertFalse(self._lock_path().exists())
        rc2, _, err2 = self._run_once()
        self.assertEqual(rc2, 0, err2)

    def test_stale_lock_reclaimed_not_treated_as_live_holder(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        self._lock_path().write_text(str(dead.pid))
        self.store.create_step("build: t", step="build", role="coder")
        rc, _, err = self._run_once()
        self.assertEqual(rc, 0, err)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertTrue(any(w["role"] == "coder" for w in workers))

    def test_clean_exit_releases_lock(self):
        self._run_once()
        self.assertFalse(self._lock_path().exists())


class TestAdd(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_new_item_is_an_untethered_todo(self):
        rc, out, err = call(_cli_mod.cmd_new, "item", "look at X later")
        self.assertEqual(rc, 0, err)
        new = out.strip()
        self.assertTrue(new)
        rc2, out2, _ = call(_cli_mod.cmd_show, new)
        t = json.loads(out2)
        self.assertEqual(t["type"], "item")
        self.assertEqual(t["state"], "backlogged")
        self.assertIsNone(t["step"])
        self.assertEqual(t["title"], "look at X later")


class TestArtifacts(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self._orig = _cli_mod._container
        _cli_mod.set_container(_cli_mod.Container(store=self.store))
        self.addCleanup(lambda: _cli_mod.set_container(self._orig))

    def test_add_and_read_artifacts_append(self):
        sid = self.store.create_item("item s", theme=self.store.create_theme("theme"))
        self.store.add_artifact(sid, "spec", "specs/X.md")
        self.store.add_artifact(sid, "pr", "https://gh/9", "PR 9")
        arts = self.store.item_artifacts(sid)
        self.assertEqual(len(arts), 2)
        self.assertEqual(arts[0].type, "spec")
        self.assertEqual(arts[1].type, "pr")
        self.assertEqual(arts[1].label, "PR 9")


class TestCompositionRoot(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self._orig = _cli_mod._container
        _cli_mod.set_container(_cli_mod.Container(store=self.store))
        self.addCleanup(lambda: _cli_mod.set_container(self._orig))

    def test_cmd_status_in_process_with_injected_store(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = _cli_mod.cmd_status(["--json"])
        self.assertEqual(ret, 0)
        s = json.loads(buf.getvalue())
        self.assertIn("inbox", s)

    def test_store_is_replaced_and_restored(self):
        self.assertIs(_cli_mod._container.store, self.store)
        _cli_mod.set_container(self._orig)
        self.assertIs(_cli_mod._container, self._orig)
        _cli_mod.set_container(_cli_mod.Container(store=self.store))


class TestLink(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_link_appends_artifact(self):
        sid = self.store.create_item("item s", theme=self.store.create_theme("theme"))
        rc, out, err = call(_cli_mod.cmd_attach, sid, "pr", "https://gh/9", "--label", "PR 9")
        self.assertEqual(rc, 0, err)
        arts = self.store.item_artifacts(sid)
        self.assertEqual(arts[0].type, "pr")
        self.assertEqual(arts[0].value, "https://gh/9")
        self.assertEqual(arts[0].label, "PR 9")


class TestModelV2(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_task_exposes_type_parent_and_parent_artifacts(self):
        theme = self.store.create_theme("theme e")
        item = self.store.create_item("item s", theme=theme)
        self.store.update_metadata(item, {"artifacts": [{"type": "spec", "value": "specs/X.md"}]})
        step = self.store.create_step("build: b", step="build", role="coder", parent=item)
        rc, out, _ = call(_cli_mod.cmd_show, step)
        v = json.loads(out)
        self.assertEqual(v["type"], "step")
        self.assertEqual(v["parent"], item)
        self.assertEqual(v["item_artifacts"][0]["value"], "specs/X.md")


class TestEpicCommand(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_epic_creates_epic_and_prints_id(self):
        rc, out, err = call(_cli_mod.cmd_new, "theme", "ship the thing")
        self.assertEqual(rc, 0, err)
        eid = out.strip()
        self.assertTrue(eid)
        self.assertEqual(self.store.get_node(eid).type, "theme")

    def test_epic_links_backlog(self):
        rc, out, _ = call(_cli_mod.cmd_new, "item", "a backlog item")
        backlog = out.strip()
        rc2, out2, err2 = call(_cli_mod.cmd_new, "theme", "ship the thing", "--backlog", backlog)
        self.assertEqual(rc2, 0, err2)
        eid = out2.strip()
        arts = self.store.item_artifacts(eid)
        self.assertEqual([(a.type, a.value) for a in arts], [("backlog", backlog)])

    def test_epic_unknown_backlog_errors(self):
        rc, _, err = call(_cli_mod.cmd_new, "theme", "ship the thing", "--backlog", "does-not-exist")
        self.assertNotEqual(rc, 0)
        self.assertIn("does-not-exist", err)


class TestFileItem(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_file_creates_story_with_spec_and_build_task(self):
        theme = self.store.create_theme("theme")
        rc, out, err = call(_file_compat, "specs/HSS-435.md", "--step", "build", "--theme", theme)
        self.assertEqual(rc, 0, err)
        sid = out.strip()
        self.assertTrue(sid)
        self.assertEqual(self.store.get_node(sid).type, "item")
        self.assertEqual(self.store.item_artifacts(sid)[0].value, "specs/HSS-435.md")
        kids = self.store.children(sid)
        self.assertEqual(len(kids), 1)
        rc2, out2, _ = call(_cli_mod.cmd_show, kids[0].id)
        self.assertEqual(json.loads(out2)["step"], "build")

    def test_file_requires_valid_epic(self):
        rc, _, err = call(
            _file_compat, "specs/HSS-435.md", "--step", "build", "--theme", "does-not-exist"
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("does-not-exist", err)

    def test_advance_parents_next_task_to_same_story(self):
        theme = self.store.create_theme("theme")
        rc, out, _ = call(_file_compat, "specs/X.md", "--step", "build", "--theme", theme)
        sid = out.strip()
        build = self.store.children(sid)[0].id
        self.store.close(build, "done")
        rc2, out2, err2 = call(_cli_mod.cmd_advance, build, "done")
        new = out2.strip()
        rc3, out3, _ = call(_cli_mod.cmd_show, new)
        nt = json.loads(out3)
        self.assertEqual(nt["parent"], sid)
        self.assertEqual(nt["step"], "review")
        self.assertEqual(nt["item_artifacts"][0]["value"], "specs/X.md")


class TestFileBlockedBy(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_blocked_by_creates_dependency_on_first_task(self):
        theme = self.store.create_theme("theme")
        gate = self.store.create_step("review-plan: foo", step="review-plan", role="human")
        rc, out, err = call(
            _file_compat, "specs/X.md", "--step", "build", "--theme", theme, "--blocked-by", gate
        )
        self.assertEqual(rc, 0, err)
        sid = out.strip()
        self.assertTrue(sid)
        node_id = self.store.children(sid)[0].id
        self.assertIn(gate, self.store._deps.get(node_id, set()))

    def test_blocked_task_not_claimable_until_gate_closes(self):
        theme = self.store.create_theme("theme")
        gate = self.store.create_step("review-plan: foo", step="review-plan", role="human")
        call(_file_compat, "specs/X.md", "--step", "build", "--theme", theme, "--blocked-by", gate)
        rc, out, _ = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(out.strip(), "")
        self.store.close(gate, "approved")
        rc2, out2, _ = call(_cli_mod.cmd_claim, "coder")
        self.assertTrue(out2.strip())

    def test_multiple_blocked_by_ids(self):
        theme = self.store.create_theme("theme")
        gate1 = self.store.create_step("gate1", role="human")
        gate2 = self.store.create_step("gate2", role="human")
        rc, out, _ = call(
            _file_compat,
            "specs/X.md",
            "--step",
            "build",
            "--theme",
            theme,
            "--blocked-by",
            gate1,
            "--blocked-by",
            gate2,
        )
        sid = out.strip()
        node_id = self.store.children(sid)[0].id
        blocker_ids = self.store._deps.get(node_id, set())
        self.assertIn(gate1, blocker_ids)
        self.assertIn(gate2, blocker_ids)


class TestClaimArtifacts(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_claim_surfaces_story_artifacts(self):
        theme = self.store.create_theme("theme")
        call(_file_compat, "specs/Y.md", "--step", "build", "--theme", theme)
        rc, out, err = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(rc, 0, err)
        t = json.loads(out)
        self.assertEqual(t["item_artifacts"][0]["value"], "specs/Y.md")

class TestTrace(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_trace_shows_story_artifacts_and_tasks(self):
        theme = self.store.create_theme("theme")
        rc, out, err = call(_file_compat, "specs/Z.md", "--step", "build", "--theme", theme)
        sid = out.strip()
        rc2, out2, err2 = call(_cli_mod.cmd_trace, sid, "--json")
        self.assertEqual(rc2, 0, err2)
        tr = json.loads(out2)
        self.assertEqual(tr["item"]["id"], sid)
        self.assertEqual(tr["artifacts"][0]["value"], "specs/Z.md")
        self.assertEqual(len(tr["steps"]), 1)
        self.assertEqual(tr["steps"][0]["step"], "build")


class TestAgentFrontmatter(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)
        (Path(self.root) / "steps").mkdir(exist_ok=True)
        (Path(self.root) / "steps" / "coder.md").write_text(
            "---\nmodel: sonnet\n---\n# Coder\n\nDo the thing.\n"
        )

    def test_parse_step_extracts_model_and_strips_frontmatter(self):
        a = _cli_mod.container().fs.parse_step("coder")
        self.assertEqual(a["meta"]["model"], "sonnet")
        self.assertTrue(a["body"].startswith("# Coder"))
        self.assertNotIn("model:", a["body"])

    def test_parse_step_reads_nested_routes(self):
        (Path(self.root) / "steps" / "reviewer.md").write_text(
            "---\nmodel: opus\nstep: review\nroutes:\n  done: open-pr\n"
            "  rejected: build\n---\n# Reviewer\n"
        )
        a = _cli_mod.container().fs.parse_step("reviewer")
        self.assertEqual(a["meta"]["step"], "review")
        self.assertEqual(a["meta"]["routes"], {"done": "open-pr", "rejected": "build"})
        self.assertTrue(a["body"].startswith("# Reviewer"))


class TestFlowFromAgents(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def _flow(self):
        return FlowService(
            _cli_mod.container().fs, _cli_mod.container().store, _cli_mod.container().config
        )

    def test_flow_next_derives_role_from_owner(self):
        t = self._flow().flow_next("build", "done")
        self.assertEqual((t.to_step, t.to_role), ("review", "reviewer"))
        t2 = self._flow().flow_next("review", "rejected")
        self.assertEqual((t2.to_step, t2.to_role), ("build", "coder"))

    def test_flow_next_unowned_target_routes_to_human(self):
        t = self._flow().flow_next("open-pr", "done")
        self.assertEqual((t.to_step, t.to_role), ("ready-merge", "human"))

    def test_flow_next_unknown_outcome_is_none(self):
        self.assertIsNone(self._flow().flow_next("build", "banana"))

    def test_flow_command_lists_steps_and_human_terminal(self):
        rc, out, err = call(_cli_mod.cmd_flow)
        self.assertEqual(rc, 0, err)
        self.assertIn("build", out)
        self.assertIn("review", out)
        self.assertIn("human", out)


class TestFileStep(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)


    def test_file_rejects_unknown_step(self):
        theme = self.store.create_theme("theme")
        rc, _, err = call(_file_compat, "specs/X.md", "--step", "bogus", "--theme", theme)
        self.assertNotEqual(rc, 0)
        self.assertIn("bogus", err)

    def test_file_starts_at_given_step(self):
        theme = self.store.create_theme("theme")
        _, out, _ = call(_file_compat, "specs/X.md", "--step", "build", "--theme", theme)
        kid = self.store.get_node(self.store.children(out.strip())[0].id)
        self.assertEqual(kid.step, "build")
        self.assertEqual(kid.role, "coder")

    def test_spawn_uses_frontmatter_model(self):
        os.environ["LC_SPAWN_CMD"] = "echo x >> {log}"
        self.addCleanup(lambda: os.environ.pop("LC_SPAWN_CMD", None))
        rc, _, err = call(_cli_mod.cmd_spawn, "coder")
        self.assertEqual(rc, 0, err)

    def test_spawn_refuses_when_model_missing(self):
        (Path(self.root) / "steps" / "reviewer.md").write_text("no frontmatter here")
        os.environ["LC_SPAWN_CMD"] = "echo x >> {log}"
        self.addCleanup(lambda: os.environ.pop("LC_SPAWN_CMD", None))
        rc, _, err = call(_cli_mod.cmd_spawn, "reviewer")
        self.assertEqual(rc, 1)
        self.assertIn("model", err)


class TestArtifactContracts(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, contract_steps=True)

    def test_claim_escalates_when_required_input_missing(self):
        b = self.store.create_step("build: x", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), "")
        step = self.store.get_node(b)
        self.assertEqual(step.role, "human")
        self.assertEqual(step.state, "ready")

    def test_claim_proceeds_when_inputs_present(self):
        theme = self.store.create_theme("theme")
        rc, out, err = call(_file_compat, "specs/X.md", "--step", "build", "--theme", theme)
        sid = out.strip()
        rc2, out2, err2 = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(rc2, 0, err2)
        t = json.loads(out2)
        self.assertEqual(t["state"], "in_progress")
        self.assertEqual(t["parent"], sid)

    def test_done_refused_when_required_output_missing(self):
        theme = self.store.create_theme("theme")
        rc, out, _ = call(_file_compat, "specs/X.md", "--step", "build", "--theme", theme)
        sid = out.strip()
        step = self.store.children(sid)[0].id
        rc2, out2, err2 = call(_cli_mod.cmd_done, step, "done")
        self.assertEqual(rc2, 1)
        self.assertIn("branch", err2)
        self.assertEqual(self.store.get_node(step).state, "ready")

    def test_done_succeeds_when_output_present(self):
        theme = self.store.create_theme("theme")
        rc, out, _ = call(_file_compat, "specs/X.md", "--step", "build", "--theme", theme)
        sid = out.strip()
        step = self.store.children(sid)[0].id
        call(_cli_mod.cmd_attach, sid, "branch", "grid/x")
        rc2, out2, err2 = call(_cli_mod.cmd_done, step, "done")
        self.assertEqual(rc2, 0, err2)
        self.assertEqual(self.store.get_node(step).state, "done")

    def test_file_rejects_non_entry_step(self):
        theme = self.store.create_theme("theme")
        rc, out, err = call(_file_compat, "specs/X.md", "--step", "review", "--theme", theme)
        self.assertEqual(rc, 1)
        self.assertIn("branch", err)

    def test_flow_reports_composition_ok(self):
        rc, out, err = call(_cli_mod.cmd_flow)
        self.assertEqual(rc, 0, err)
        self.assertIn("branch", out)

    def test_flow_flags_broken_composition(self):
        specs = {k: dict(v) for k, v in _CONTRACT_SPECS.items()}
        specs["reviewer"] = dict(
            specs["reviewer"], accepts={"spec": "required", "design": "required"}
        )
        write_contract_steps(self.root, specs)
        rc, out, err = call(_cli_mod.cmd_flow)
        self.assertEqual(rc, 1)
        self.assertIn("design", err)


class TestPruneWorkers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = new_store()
        (Path(cls.root) / "logs").mkdir(exist_ok=True)

    def setUp(self):
        self.wfile = Path(self.root) / "logs" / "workers.json"
        os.environ["LC_CONFIG"] = write_config(projects=self.root, specs=self.root)
        self.addCleanup(lambda: os.environ.__setitem__("LC_CONFIG", _ABSENT_CONFIG))

    def _dead_pid(self):
        p = subprocess.Popen(["true"])
        p.wait()
        return p.pid

    def _write(self, workers):
        self.wfile.write_text(json.dumps(workers))

    def _sweep(self, history=None):
        env = dict(os.environ, LC_ROOT_OVERRIDE=self.root)
        if history is not None:
            env["LC_WORKER_HISTORY"] = str(history)
        return subprocess.run(
            [sys.executable, TG, "sweep"], capture_output=True, text=True, env=env
        )

    def test_sweep_prunes_dead_keeps_live(self):
        dead = self._dead_pid()
        self._write(
            [
                {
                    "spawnid": "a",
                    "role": "coder",
                    "pid": os.getpid(),
                    "log": "x",
                    "step": None,
                    "started": time.time(),
                },
                {"spawnid": "b", "role": "coder", "pid": dead, "log": "y", "step": None},
            ]
        )
        r = self._sweep(history=0)
        self.assertEqual(r.returncode, 0, r.stderr)
        ids = [w["spawnid"] for w in json.loads(self.wfile.read_text())]
        self.assertEqual(ids, ["a"])

    def test_sweep_keeps_recent_dead_for_log_lookup(self):
        dead = self._dead_pid()
        self._write(
            [
                {"spawnid": "d%d" % i, "role": "coder", "pid": dead, "log": "l", "step": None}
                for i in range(3)
            ]
        )
        self._sweep(history=2)
        ids = [w["spawnid"] for w in json.loads(self.wfile.read_text())]
        self.assertEqual(ids, ["d1", "d2"])


class TestInitAndStoreGuard(unittest.TestCase):
    def _bare(self):
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        return d

    def _cfg(self, d):
        return os.path.join(d, "grid-config")

    def test_init_creates_store_and_is_idempotent(self):
        d = self._bare()
        cfg = self._cfg(d)
        r = run_tg("init", root=d, config=cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(d, "store.db")))
        r2 = run_tg("init", root=d, config=cfg)
        self.assertEqual(r2.returncode, 0, r2.stderr)

    def test_run_without_store_errors(self):
        d = self._bare()
        r = run_tg("start", "--once", root=d)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("init", r.stderr)

    def test_up_is_gone(self):
        r = run_tg("up")
        self.assertEqual(r.returncode, 2)


class TestContractsOptional(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_done_without_contract_needs_no_artifacts(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "done")
        self.assertEqual(rc, 0, err)


class TestWorktree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = tempfile.mkdtemp()
        cls.root = make_repo(parent, "engine")
        write_steps(cls.root)

    def setUp(self):
        os.environ["LC_CONFIG"] = write_config(
            projects=os.path.dirname(self.root), specs=self.root
        )
        os.environ["LC_ROOT_OVERRIDE"] = self.root
        self.store = FakeStore()
        self._orig = _cli_mod._container
        _cli_mod.set_container(_cli_mod.Container(store=self.store))
        self.addCleanup(lambda: _cli_mod.set_container(self._orig))
        self.addCleanup(lambda: os.environ.pop("LC_ROOT_OVERRIDE", None))

    def tearDown(self):
        os.environ["LC_CONFIG"] = _ABSENT_CONFIG
        _reset_git_repo(self.root)

    def _branch_of(self, path):
        return git_in(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def _file(self):
        theme = self.store.create_theme("theme")
        _, out, _ = call(_file_compat, "specs/W.md", "--step", "build", "--theme", theme)
        return out.strip()

    def test_claim_returns_isolated_workspace(self):
        sid = self._file()
        _, out, err = call(_cli_mod.cmd_claim, "coder")
        t = json.loads(out)
        ws = t["workspace"]
        self.assertTrue(os.path.isdir(ws))
        self.assertEqual(os.path.basename(ws), sid)
        self.assertEqual(os.path.dirname(ws), os.path.join(self.root, ".worktrees"))
        self.assertEqual(self._branch_of(ws), "feat/w")
        self.assertEqual(t["branch"], "feat/w")

    def test_claim_does_not_switch_root_branch(self):
        self._file()
        before = self._branch_of(self.root)
        call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(self._branch_of(self.root), before)
        self.assertEqual(self._branch_of(self.root), "main")

    def test_worktree_reused_across_roles(self):
        sid = self._file()
        _, out, _ = call(_cli_mod.cmd_claim, "coder")
        ws1 = json.loads(out)["workspace"]
        build = self.store.children(sid)[0].id
        call(_cli_mod.cmd_done, build, "done")
        _, out2, _ = call(_cli_mod.cmd_claim, "reviewer")
        ws2 = json.loads(out2)["workspace"]
        self.assertEqual(ws1, ws2)

    def test_branch_artifact_autolinked_on_claim(self):
        sid = self._file()
        call(_cli_mod.cmd_claim, "coder")
        arts = self.store.item_artifacts(sid)
        branches = [a for a in arts if a.type == "branch"]
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0].value, "feat/w")

    def test_worktrees_dir_gitignored(self):
        self._file()
        call(_cli_mod.cmd_claim, "coder")
        gi = (Path(self.root) / ".gitignore").read_text().splitlines()
        self.assertIn(".worktrees/", [l.strip() for l in gi])

    def test_reclaim_reuses_existing_branch(self):
        sid = self._file()
        ws = _cli_mod._worktrees().ensure(sid)
        (Path(ws) / "f.txt").write_text("x")
        git_in(ws, "add", ".")
        git_in(ws, "commit", "-q", "-m", "w")
        git_in(self.root, "worktree", "remove", "--force", ws)
        self.assertFalse(os.path.isdir(ws))
        ws2 = _cli_mod._worktrees().ensure(sid)
        self.assertEqual(ws, ws2)
        self.assertEqual(self._branch_of(ws2), "feat/w")
        self.assertTrue(os.path.isfile(os.path.join(ws2, "f.txt")))


class TestWorktreeNoOrigin(unittest.TestCase):
    def setUp(self):
        parent = tempfile.mkdtemp()
        self.root = os.path.join(parent, "engine")
        subprocess.run(["git", "init", "-q", self.root], check=True)
        write_steps(self.root)
        os.environ["LC_CONFIG"] = write_config(projects=parent, specs=self.root)
        os.environ["LC_ROOT_OVERRIDE"] = self.root
        self.store = FakeStore()
        self._orig = _cli_mod._container
        _cli_mod.set_container(_cli_mod.Container(store=self.store))
        self.addCleanup(lambda: _cli_mod.set_container(self._orig))
        self.addCleanup(lambda: os.environ.pop("LC_ROOT_OVERRIDE", None))

    def tearDown(self):
        os.environ["LC_CONFIG"] = _ABSENT_CONFIG

    def test_claim_omits_workspace_without_origin(self):
        self.store.create_step("build: t", step="build", role="coder")
        _, out, _ = call(_cli_mod.cmd_claim, "coder")
        t = json.loads(out)
        self.assertEqual(t["state"], "in_progress")
        self.assertNotIn("workspace", t)


class TestNamedRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.projects = tempfile.mkdtemp()
        cls.engine = make_repo(cls.projects, "engine")
        write_steps(cls.engine)
        cls.app = make_repo(cls.projects, "app")

    def setUp(self):
        os.environ["LC_CONFIG"] = write_config(projects=self.projects, specs=self.engine)
        os.environ["LC_ROOT_OVERRIDE"] = self.engine
        self.store = FakeStore()
        self._orig = _cli_mod._container
        _cli_mod.set_container(_cli_mod.Container(store=self.store))
        self.addCleanup(lambda: _cli_mod.set_container(self._orig))
        self.addCleanup(lambda: os.environ.pop("LC_ROOT_OVERRIDE", None))

    def tearDown(self):
        os.environ["LC_CONFIG"] = _ABSENT_CONFIG
        _reset_git_repo(self.engine)
        _reset_git_repo(self.app)

    def _has_branch(self, repo, branch):
        return (
            subprocess.run(
                ["git", "-C", repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch],
                capture_output=True,
            ).returncode
            == 0
        )

    def _claim(self, repo=None):
        theme = self.store.create_theme("theme")
        args = ["specs/X.md", "--step", "build", "--theme", theme]
        if repo:
            args += ["--repo", repo]
        call(_file_compat, *args)
        rc, out, err = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def test_named_repo_worktree_created_engine_untouched(self):
        view = self._claim("app")
        branch = "feat/x"
        self.assertEqual(view["workspace"], os.path.join(self.engine, ".worktrees", view["parent"]))
        self.assertTrue(os.path.isdir(view["workspace"]))
        self.assertTrue(self._has_branch(self.app, branch))
        self.assertFalse(self._has_branch(self.engine, branch))

    def test_default_repo_targets_self(self):
        view = self._claim()
        branch = "feat/x"
        self.assertTrue(os.path.isdir(view["workspace"]))
        self.assertTrue(self._has_branch(self.engine, branch))
        self.assertFalse(self._has_branch(self.app, branch))

    def test_claim_includes_absolute_spec_path(self):
        view = self._claim("app")
        self.assertTrue(os.path.isabs(view["spec_path"]))
        self.assertTrue(view["spec_path"].endswith("specs/X.md"))
        self.assertTrue(view["spec_path"].startswith(self.engine))

    def test_file_stores_single_repo_artifact(self):
        theme = self.store.create_theme("theme")
        _, out, _ = call(
            _file_compat, "specs/X.md", "--step", "build", "--theme", theme, "--repo", "app"
        )
        arts = self.store.item_artifacts(out.strip())
        repos = [a.value for a in arts if a.type == "repo"]
        self.assertEqual(repos, ["app"])


class TestUnblock(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_unblock_returns_blocked_task_to_agent_role(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        self.store.claim_ready("coder")
        call(_cli_mod.cmd_set, b, "--state", "blocked", "--needs", "rebase first")
        rc, out, err = call(_cli_mod.cmd_set, b, "--state", "ready")
        self.assertEqual(rc, 0, err)
        t = self.store.get_node(b)
        self.assertEqual(t.state, "ready")
        self.assertEqual(t.role, "coder")
        self.assertIsNone(t.claimed_by)

    def test_unblock_clears_needs_and_blocked_note(self):
        b = self.store.create_step("build: t", step="build", role="coder")
        self.store.claim_ready("coder")
        call(_cli_mod.cmd_set, b, "--state", "blocked", "--needs", "rebase first")
        rc, out, err = call(_cli_mod.cmd_set, b, "--state", "ready")
        self.assertEqual(rc, 0, err)
        t = self.store.get_node(b)
        self.assertIsNone(t.needs)
        self.assertNotIn("BLOCKED:", t.notes or "")

    def test_unblock_refuses_human_step(self):
        (Path(self.root) / "steps" / "ready-merge.md").write_text(
            "---\nstep: ready-merge\nroutes:\n  merged: cleanup\n---\n# ready-merge\n"
        )
        b = self.store.create_step("ready-merge: t", step="ready-merge", role="human")
        rc, out, err = call(_cli_mod.cmd_set, b, "--state", "ready")
        self.assertEqual(rc, 1)
        self.assertIn("ready-merge", err)


class TestCloseWorktree(unittest.TestCase):
    def setUp(self):
        parent = tempfile.mkdtemp()
        self.root = make_repo(parent, "engine")
        write_steps(self.root)
        os.environ["LC_CONFIG"] = write_config(projects=parent, specs=self.root)
        os.environ["LC_ROOT_OVERRIDE"] = self.root
        self.store = FakeStore()
        self._orig = _cli_mod._container
        _cli_mod.set_container(_cli_mod.Container(store=self.store))
        self.addCleanup(lambda: _cli_mod.set_container(self._orig))
        self.addCleanup(lambda: os.environ.pop("LC_ROOT_OVERRIDE", None))

    def tearDown(self):
        os.environ["LC_CONFIG"] = _ABSENT_CONFIG

    def _has_branch(self, repo, branch):
        return (
            subprocess.run(
                ["git", "-C", repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch],
                capture_output=True,
            ).returncode
            == 0
        )

    def test_close_closes_story_and_tasks_and_removes_worktree(self):
        theme = self.store.create_theme("theme")
        _, out, _ = call(_file_compat, "specs/W.md", "--step", "build", "--theme", theme)
        sid = out.strip()
        _, cout, _ = call(_cli_mod.cmd_claim, "coder")
        ws = json.loads(cout)["workspace"]
        self.assertTrue(os.path.isdir(ws))
        build = self.store.children(sid)[0].id
        rc, _, err = call(_cli_mod.cmd_done, sid, "merged")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.get_node(sid).state, "done")
        self.assertEqual(self.store.get_node(build).state, "done")
        self.assertFalse(os.path.isdir(ws))
        self.assertFalse(self._has_branch(self.root, "feat/w"))


class TestClose(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_close_theme_closes_when_all_stories_closed(self):
        theme = self.store.create_theme("theme e")
        child = self.store.create_item("item s", theme=theme)
        self.store.close(child, "merged")
        rc, out, err = call(_cli_mod.cmd_done, theme, "done")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.get_node(theme).state, "done")

    def test_close_epic_refuses_with_open_story(self):
        theme = self.store.create_theme("theme e")
        child = self.store.create_item("item s", theme=theme)
        rc, _, err = call(_cli_mod.cmd_done, theme, "done")
        self.assertEqual(rc, 1)
        self.assertIn(child, err)
        self.assertEqual(self.store.get_node(theme).state, "ready")

    def test_close_epic_refuses_does_not_cascade_close_open_stories(self):
        theme = self.store.create_theme("theme e")
        child = self.store.create_item("item s", theme=theme)
        call(_cli_mod.cmd_done, theme, "done")
        self.assertEqual(self.store.get_node(child).state, "backlogged")

    def test_close_epic_attaches_no_retro_artifact(self):
        theme = self.store.create_theme("theme e")
        child = self.store.create_item("item s", theme=theme)
        self.store.create_step("build: t", step="build", role="coder", parent=child)
        claimed = self.store.claim_ready("coder")
        self.store.close(claimed.id, "done")
        self.store.close(child, "merged")
        rc, out, err = call(_cli_mod.cmd_done, theme, "done")
        self.assertEqual(rc, 0, err)
        self.assertEqual([a for a in self.store.item_artifacts(theme) if a.type == "retro"], [])


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.dir = tempfile.mkdtemp()
        self.cfg = os.path.join(self.dir, "config")
        os.environ["LC_ROOT_OVERRIDE"] = self.root
        os.environ["LC_CONFIG"] = self.cfg
        self.store = FakeStore()
        self._orig = _cli_mod._container
        _cli_mod.set_container(_cli_mod.Container(store=self.store))
        self.addCleanup(lambda: _cli_mod.set_container(self._orig))
        self.addCleanup(lambda: os.environ.pop("LC_ROOT_OVERRIDE", None))
        self.addCleanup(lambda: os.environ.__setitem__("LC_CONFIG", _ABSENT_CONFIG))

    def test_config_prints_path_and_unset_roots(self):
        rc, out, err = call(_cli_mod.cmd_config)
        self.assertEqual(rc, 0, err)
        self.assertIn(self.cfg, out)
        self.assertIn("not found", out)
        self.assertIn("projects: (not set", out)
        self.assertIn("specs: (not set", out)

    def test_init_seeds_config_when_absent_and_is_idempotent(self):
        self.assertFalse(os.path.exists(self.cfg))
        rc, out, err = call(_cli_mod.cmd_init)
        self.assertEqual(rc, 0, err)
        self.assertIn("created", out)
        self.assertTrue(os.path.exists(self.cfg))
        self.assertIn("~/workspace/projects", Path(self.cfg).read_text())
        rc2, out2, err2 = call(_cli_mod.cmd_init)
        self.assertEqual(rc2, 0, err2)
        self.assertIn("already exists", out2)

    def test_written_config_overrides_roots(self):
        proj = tempfile.mkdtemp()
        specs = tempfile.mkdtemp()
        Path(self.cfg).write_text("projects: %s\nspecs: %s\n" % (proj, specs))
        rc, out, err = call(_cli_mod.cmd_config)
        self.assertEqual(rc, 0, err)
        self.assertIn("projects: %s" % proj, out)
        self.assertIn("specs: %s" % specs, out)

    def test_init_tops_up_existing_config_with_missing_keys(self):
        Path(self.cfg).write_text("projects: /p\nspecs: /s\n")
        rc, out, err = call(_cli_mod.cmd_init)
        self.assertEqual(rc, 0, err)
        self.assertIn("created", out)
        text = Path(self.cfg).read_text()
        self.assertIn("max-agents: 5", text)
        self.assertIn("projects: /p", text)


class TestLogRender(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)
        (Path(self.root) / "logs").mkdir(exist_ok=True)
        self.log = Path(self.root) / "logs" / "worker-coder-x.log"
        self.log.write_text(
            "\n".join(
                [
                    json.dumps({"type": "system", "subtype": "init"}),
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [{"type": "text", "text": "Claiming the step."}]
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "name": "Bash",
                                        "input": {"command": "tg claim coder"},
                                    }
                                ]
                            },
                        }
                    ),
                    json.dumps({"type": "result", "result": "done; banner fixed"}),
                ]
            )
            + "\n"
        )
        (Path(self.root) / "logs" / "workers.json").write_text(
            json.dumps(
                [
                    {
                        "spawnid": "x",
                        "role": "coder",
                        "pid": os.getpid(),
                        "log": str(self.log),
                        "step": None,
                        "started": time.time(),
                    }
                ]
            )
        )

    def test_logs_renders_stream_json(self):
        rc, out, err = call(_cli_mod.cmd_logs, "coder")
        self.assertEqual(rc, 0, err)
        self.assertIn("Claiming the step.", out)
        self.assertIn("$ tg claim coder", out)
        self.assertIn("done; banner fixed", out)
        self.assertNotIn('"type"', out)


class TestInboxBacklog(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)
        adir = Path(self.root) / "steps"
        adir.mkdir(exist_ok=True)
        (adir / "coder.md").write_text(
            "---\nmodel: sonnet\nstep: build\nroutes:\n  done: review\n---\nstub"
        )
        (adir / "ready-merge.md").write_text(
            "---\nstep: ready-merge\nroutes:\n  merged: cleanup\n  changes: build\n---\nstub"
        )
        write_workflow_from_steps(self.root)

    def test_inbox_shows_action_and_blocked_only(self):
        call(_cli_mod.cmd_new, "item", "a seed")
        self.store.create_step("merge: z", step="ready-merge", role="human")
        self.store.create_step("build: q", step="build", role="human")
        _, out, _ = call(_cli_mod.cmd_inbox)
        self.assertIn("[action]", out)
        self.assertIn("[blocked]", out)
        self.assertNotIn("[todo]", out)
        self.assertNotIn("a seed", out)

    def test_backlog_shows_todo_only(self):
        call(_cli_mod.cmd_new, "item", "a seed")
        self.store.create_step("merge: z", step="ready-merge", role="human")
        _, out, _ = call(_cli_mod.cmd_backlog)
        self.assertIn("[todo]", out)
        self.assertIn("a seed", out)
        self.assertNotIn("[action]", out)

    def test_inbox_limit_n(self):
        self.store.create_step("merge: p", step="ready-merge", role="human")
        self.store.create_step("merge: q", step="ready-merge", role="human")
        self.store.create_step("merge: r", step="ready-merge", role="human")
        _, out, _ = call(_cli_mod.cmd_inbox, "1")
        self.assertEqual(len([l for l in out.splitlines() if l.strip()]), 1)

    def test_backlog_limit_n(self):
        call(_cli_mod.cmd_new, "item", "seed one")
        call(_cli_mod.cmd_new, "item", "seed two")
        call(_cli_mod.cmd_new, "item", "seed three")
        _, out, _ = call(_cli_mod.cmd_backlog, "2")
        self.assertEqual(len([l for l in out.splitlines() if l.strip()]), 2)

    def test_inbox_shows_plan_doc_for_gate_task(self):
        tid = self.store.create_step("merge: gate", step="ready-merge", role="human")
        self.store.add_artifact(tid, "plan-doc", "/docs/plan.md")
        _, out, _ = call(_cli_mod.cmd_inbox)
        self.assertIn("plan:/docs/plan.md", out)


class TestReflect(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def _file_story(self, spec_path=None):
        sid = self.store.create_item("feat", theme=self.store.create_theme("theme"))
        self.store.update_metadata(
            sid, {"artifacts": [{"type": "spec", "value": spec_path or "/tmp/no-spec.md"}]}
        )
        tid = self.store.create_step("build: feat", step="build", role="coder", parent=sid)
        return sid, tid

    def test_reflect_stores_feedback_on_task(self):
        sid, tid = self._file_story()
        rc, out, err = call(
            _cli_mod.cmd_attach, tid, "feedback", "pytest not found; spec thin on errors"
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(
            self.store.item_artifacts(sid), [Artifact(type="spec", value="/tmp/no-spec.md")]
        )
        refs = [a for a in self.store.item_artifacts(tid) if a.type == "reflection"]
        self.assertEqual(len(refs), 1)
        data = json.loads(refs[0].value)
        self.assertEqual(data["feedback"], "pytest not found; spec thin on errors")
        self.assertEqual(data["step"], tid)

    def test_reflect_multiple_calls_append(self):
        sid, tid = self._file_story()
        call(_cli_mod.cmd_attach, tid, "feedback", "first")
        call(_cli_mod.cmd_attach, tid, "feedback", "second")
        refs = [a for a in self.store.item_artifacts(tid) if a.type == "reflection"]
        self.assertEqual(len(refs), 2)

    def test_reflect_stamps_spec_hash(self):
        import tempfile as _tmpfile

        spec = _tmpfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
        spec.write("# spec\ncontent")
        spec.close()
        sid, tid = self._file_story(spec_path=spec.name)
        self.store.update_metadata(sid, {"artifacts": [{"type": "spec", "value": spec.name}]})
        call(_cli_mod.cmd_attach, tid, "feedback", "ok")
        data = json.loads(
            next(a for a in self.store.item_artifacts(tid) if a.type == "reflection").value
        )
        self.assertNotEqual(data["spec_hash"], "unknown")
        self.assertEqual(len(data["spec_hash"]), 8)

    def test_reflect_no_feedback_still_valid(self):
        sid, tid = self._file_story()
        rc, out, err = call(_cli_mod.cmd_attach, tid, "feedback", "")
        self.assertEqual(rc, 0, err)
        data = json.loads(
            next(a for a in self.store.item_artifacts(tid) if a.type == "reflection").value
        )
        self.assertEqual(data["feedback"], "")


class TestRetro(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def _make_epic_with_story(self, sid=None):
        theme = self.store.create_theme("theme-1")
        if sid is None:
            sid = self.store.create_item("item-1", theme=theme)
        return theme, sid

    def test_retro_no_reflections(self):
        theme, _ = self._make_epic_with_story()
        rc, out, err = call(_cli_mod.cmd_retro, theme)
        self.assertEqual(rc, 0, err)
        self.assertIn("N=0", out)
        self.assertIn("no reflections yet", out)
        self.assertIn("Per-item signals", out)

    def test_retro_shows_feedback(self):
        theme, sid = self._make_epic_with_story()
        tid = self.store.create_step("build: s", step="build", role="coder", parent=sid)
        call(_cli_mod.cmd_attach, tid, "feedback", "edge case coverage was thin")
        rc, out, err = call(_cli_mod.cmd_retro, theme)
        self.assertEqual(rc, 0, err)
        self.assertIn("N=1", out)
        self.assertIn("Feedback", out)
        self.assertIn("edge case coverage was thin", out)

    def test_retro_surfaces_epic_level_feedback(self):
        theme, _ = self._make_epic_with_story()
        ptid = self.store.create_step("plan: e", step="plan", role="planner", parent=theme)
        call(_cli_mod.cmd_attach, ptid, "feedback", "brief was thin on dep ordering")
        rc, out, err = call(_cli_mod.cmd_retro, theme)
        self.assertEqual(rc, 0, err)
        self.assertIn("brief was thin on dep ordering", out)

    def test_retro_signals_review_rounds(self):
        theme, sid = self._make_epic_with_story()
        self.store.create_step("review: s", step="review", role="reviewer", parent=sid)
        rtid = self.store.create_step("review: s2", step="review", role="reviewer", parent=sid)
        self.store.close(rtid, "rejected")
        rc, out, err = call(_cli_mod.cmd_retro, theme)
        self.assertEqual(rc, 0, err)
        self.assertIn("review_rounds=1", out)

    def test_retro_signals_conflict(self):
        theme, sid = self._make_epic_with_story()
        pr_tid = self.store.create_step("open-pr: s", step="open-pr", role="pr-watcher", parent=sid)
        self.store.close(pr_tid, "conflict-rebase")
        rc, out, err = call(_cli_mod.cmd_retro, theme)
        self.assertEqual(rc, 0, err)
        self.assertIn("conflicts=1", out)

    def test_retro_shows_story_duration_for_claimed_and_closed_task(self):
        theme, sid = self._make_epic_with_story()
        self.store.create_step("build: s", step="build", role="coder", parent=sid)
        claimed = self.store.claim_ready("coder")
        self.store.close(claimed.id, "done")
        rc, out, err = call(_cli_mod.cmd_retro, theme)
        self.assertEqual(rc, 0, err)
        self.assertRegex(out, r"duration=\d")

    def test_retro_shows_unknown_duration_when_task_never_claimed(self):
        theme, sid = self._make_epic_with_story()
        tid = self.store.create_step("build: s", step="build", role="coder", parent=sid)
        self.store.close(tid, "done")
        rc, out, err = call(_cli_mod.cmd_retro, theme)
        self.assertEqual(rc, 0, err)
        self.assertIn("duration=unknown", out)


class TestWorklog(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def _close_story(self, title="feat: shipped-thing", reason="merged"):
        sid = self.store.create_item(title, theme=self.store.create_theme("theme"))
        self.store.close(sid, reason)
        return sid

    def test_worklog_no_args_shows_stories_closed_today(self):
        sid = self._close_story()
        rc, out, err = call(_cli_mod.cmd_worklog)
        self.assertEqual(rc, 0, err)
        self.assertIn(sid, out)
        self.assertIn("merged", out)

    def test_worklog_today_keyword_shows_story(self):
        sid = self._close_story()
        rc, out, err = call(_cli_mod.cmd_worklog, "today")
        self.assertEqual(rc, 0, err)
        self.assertIn(sid, out)

    def test_worklog_yesterday_shows_nothing_for_todays_story(self):
        self._close_story()
        rc, out, err = call(_cli_mod.cmd_worklog, "yesterday")
        self.assertEqual(rc, 0, err)
        self.assertIn("no items", out)

    def test_worklog_two_arg_range_includes_today(self):
        import datetime

        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        today = datetime.date.today().isoformat()
        sid = self._close_story()
        rc, out, err = call(_cli_mod.cmd_worklog, yesterday, today)
        self.assertEqual(rc, 0, err)
        self.assertIn(sid, out)

    def test_worklog_empty_period_prints_no_stories_message(self):
        rc, out, err = call(_cli_mod.cmd_worklog, "2020-01-01")
        self.assertEqual(rc, 0, err)
        self.assertIn("no items", out)

    def test_worklog_shows_pr_link_when_present(self):
        sid = self._close_story()
        self.store.update_metadata(
            sid, {"artifacts": [{"type": "pr", "value": "https://github.com/x/y/pull/9"}]}
        )
        rc, out, err = call(_cli_mod.cmd_worklog)
        self.assertEqual(rc, 0, err)
        self.assertIn("https://github.com/x/y/pull/9", out)

    def test_worklog_no_pr_artifact_still_lists_story(self):
        sid = self._close_story()
        rc, out, err = call(_cli_mod.cmd_worklog)
        self.assertEqual(rc, 0, err)
        self.assertIn(sid, out)
        self.assertNotIn("https://", out)

    def test_worklog_excludes_tasks(self):
        self.store.create_step("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_worklog)
        self.assertEqual(rc, 0, err)
        self.assertIn("no items", out)

    def test_worklog_shows_title_and_outcome(self):
        self._close_story(title="shipped-thing", reason="done")
        rc, out, err = call(_cli_mod.cmd_worklog)
        self.assertEqual(rc, 0, err)
        self.assertIn("shipped-thing", out)
        self.assertIn("done", out)

    def test_worklog_appears_in_help(self):
        r = run_tg("--help")
        self.assertIn("worklog", r.stdout)


class TestCadenceStepDTO(unittest.TestCase):
    """Verifies that the CLI DTO emitted by tg show / tg claim includes 'since'."""

    def setUp(self):
        _fake_setUp(self)

    def test_show_cadence_task_includes_since(self):
        tid = self.store.create_step("trend: window", step="audit", role="auditor")
        self.store.update_metadata(tid, {"since": "2025-12-01", "fired_at": "2026-01-01"})
        rc, out, err = call(_cli_mod.cmd_show, tid)
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        self.assertEqual(d["since"], "2025-12-01")
        self.assertEqual(d["fired_at"], "2026-01-01")

    def test_claim_cadence_task_includes_since(self):
        tid = self.store.create_step("trend: window", step="audit", role="auditor")
        self.store.update_metadata(tid, {"since": "2025-12-01", "fired_at": "2026-01-01"})
        rc, out, err = call(_cli_mod.cmd_claim, "auditor")
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        self.assertEqual(d["id"], tid)
        self.assertEqual(d["since"], "2025-12-01")
        self.assertEqual(d["fired_at"], "2026-01-01")


class TestNodeDTOReadSurface(unittest.TestCase):
    AGENT_CONSUMED_FIELDS = (
        "id", "parent", "step", "state", "artifacts", "description",
        "notes", "theme", "since", "fired_at", "closed_at", "attention",
    )

    def setUp(self):
        _fake_setUp(self)

    def _make_task(self):
        tid = self.store.create_step("build: t", step="build", role="coder")
        self.store.update_metadata(tid, {"since": "2025-12-01", "fired_at": "2026-01-01"})
        return tid

    def test_show_surfaces_agent_consumed_fields(self):
        tid = self._make_task()
        rc, out, err = call(_cli_mod.cmd_show, tid)
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        for field in self.AGENT_CONSUMED_FIELDS:
            self.assertIn(field, d, "tg show dropped field: %s" % field)

    def test_claim_surfaces_agent_consumed_fields(self):
        tid = self._make_task()
        rc, out, err = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        self.assertEqual(d["id"], tid)
        for field in self.AGENT_CONSUMED_FIELDS:
            self.assertIn(field, d, "tg claim dropped field: %s" % field)


class TestWorktreePushTarget(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.mkdtemp()
        self.repo = make_repo(self.parent, "app")
        self.worktrees_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.parent, True)
        self.addCleanup(shutil.rmtree, self.worktrees_dir, True)

    def _svc(self, store):
        parent = self.parent
        wt_dir = self.worktrees_dir

        class _Fs:
            def worktrees_dir(self):
                return wt_dir

            def ensure_worktrees_ignored(self):
                pass

        class _Cfg:
            def projects_root(self):
                return parent

            def engine_root(self):
                return parent

            def worktree_retries(self):
                return 2

            def worktree_retry_sleep(self):
                return 0.1

        return WorktreeService(store, GitAdapter(), _Fs(), _Cfg())

    def _git(self, path, *args):
        return subprocess.run(["git", "-C", path] + list(args),
                              capture_output=True, text=True)

    def _make_store(self, branch="feat/my-feat"):
        store = FakeStore()
        sid = store.create_item("my-feat", theme=store.create_theme("theme"))
        store.add_artifact(sid, "repo", "app")
        store.add_artifact(sid, "branch", branch)
        return store, sid

    def test_branch_tracking_targets_feature_not_main(self):
        store, sid = self._make_store()
        ws = self._svc(store).ensure(sid)
        self.assertIsNotNone(ws)

        remote = self._git(self.repo, "config", "branch.feat/my-feat.remote").stdout.strip()
        merge = self._git(self.repo, "config", "branch.feat/my-feat.merge").stdout.strip()
        self.assertEqual(remote, "origin")
        self.assertEqual(merge, "refs/heads/feat/my-feat")

    def test_bare_force_push_lands_on_feature_branch(self):
        store, sid = self._make_store()
        ws = self._svc(store).ensure(sid)
        self.assertIsNotNone(ws)

        (Path(ws) / "f.txt").write_text("hello")
        git_in(ws, "add", "f.txt")
        git_in(ws, "commit", "-m", "wip")

        r = subprocess.run(["git", "push", "--force-with-lease"],
                           cwd=ws, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

        ls = self._git(self.repo, "ls-remote", "--heads", "origin").stdout
        self.assertIn("refs/heads/feat/my-feat", ls)

        remote_feat_sha = self._git(self.repo, "rev-parse",
                                    "origin/feat/my-feat").stdout.strip()
        ws_head_sha = self._git(ws, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(remote_feat_sha, ws_head_sha)

        remote_main_sha = self._git(self.repo, "rev-parse", "origin/main").stdout.strip()
        self.assertNotEqual(remote_main_sha, ws_head_sha)

    def test_second_bare_force_push_after_amend_updates_feature_branch(self):
        store, sid = self._make_store()
        ws = self._svc(store).ensure(sid)
        self.assertIsNotNone(ws)

        (Path(ws) / "f.txt").write_text("v1")
        git_in(ws, "add", "f.txt")
        git_in(ws, "commit", "-m", "first")
        subprocess.run(["git", "push", "--force-with-lease"], cwd=ws,
                       check=True, capture_output=True)

        (Path(ws) / "f.txt").write_text("v2")
        git_in(ws, "add", "f.txt")
        git_in(ws, "commit", "--amend", "--no-edit")

        r = subprocess.run(["git", "push", "--force-with-lease"],
                           cwd=ws, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

        remote_sha = self._git(self.repo, "rev-parse",
                               "origin/feat/my-feat").stdout.strip()
        local_sha = self._git(ws, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(remote_sha, local_sha)


class TestWorkflowSelection(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)
        (Path(self.root) / "workflows" / "solo.md").write_text(
            "entry: build\n\nnodes:\n  build  coder\n"
        )

    def _epic(self, *args):
        _, out, err = call(_cli_mod.cmd_new, "theme", *args)
        return out.strip()

    def _file(self, spec, theme, *args):
        _, out, err = call(_file_compat, spec, "--theme", theme, *args)
        return out.strip()

    def _build_task(self, item):
        return next(
            t for t in self.store.all_nodes() if t.parent == item and t.step == "build"
        )

    def _open_successor_steps(self, item):
        return {t.step for t in self.store.all_nodes() if t.parent == item and t.step != "build"}

    def test_two_epics_route_by_their_own_workflow(self):
        std_epic = self._epic("standard objective")
        std_story = self._file("A.md", std_epic)
        solo_epic = self._epic("solo objective", "--workflow", "solo")
        solo_story = self._file("B.md", solo_epic)

        call(_cli_mod.cmd_done, self._build_task(std_story).id, "done")
        self.assertIn("review", self._open_successor_steps(std_story))

        call(_cli_mod.cmd_done, self._build_task(solo_story).id, "done")
        self.assertEqual(self._open_successor_steps(solo_story), set())

    def test_file_derives_entry_step_from_the_workflow(self):
        theme = self._epic("obj")
        item = self._file("A.md", theme)
        self.assertEqual(self._build_task(item).step, "build")

    def test_epic_workflow_is_inherited_without_stamping_the_story(self):
        theme = self._epic("obj", "--workflow", "solo")
        item = self._file("A.md", theme)
        self.assertEqual(self.store.get_node(theme).workflow, "solo")
        self.assertIsNone(self.store.get_node(item).workflow)

    def test_story_can_override_the_epic_workflow(self):
        theme = self._epic("obj")
        item = self._file("A.md", theme, "--workflow", "solo")
        self.assertEqual(self.store.get_node(item).workflow, "solo")
        call(_cli_mod.cmd_done, self._build_task(item).id, "done")
        self.assertEqual(self._open_successor_steps(item), set())


class TestProjectWorkflowOverride(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)
        pdir = Path(self.root) / "myapp" / ".lightcycle" / "workflows"
        pdir.mkdir(parents=True)
        (pdir / "standard.md").write_text("entry: build\n\nnodes:\n  build  coder\n")

    def _build_task(self, item):
        return next(
            t for t in self.store.all_nodes() if t.parent == item and t.step == "build"
        )

    def _successors(self, item):
        return {t.step for t in self.store.all_nodes() if t.parent == item and t.step != "build"}

    def test_a_project_grid_workflow_shadows_the_default_for_that_project(self):
        theme = call(_cli_mod.cmd_new, "theme", "obj")[1].strip()
        item = call(_file_compat, "A.md", "--theme", theme, "--project", "myapp")[1].strip()
        call(_cli_mod.cmd_done, self._build_task(item).id, "done")
        self.assertEqual(self._successors(item), set())

    def test_a_story_without_that_project_uses_the_default(self):
        theme = call(_cli_mod.cmd_new, "theme", "obj2")[1].strip()
        item = call(_file_compat, "B.md", "--theme", theme)[1].strip()
        call(_cli_mod.cmd_done, self._build_task(item).id, "done")
        self.assertIn("review", self._successors(item))


if __name__ == "__main__":
    unittest.main()
