import io, json, os, shutil, subprocess, sys, tempfile, time, unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TG = str(ROOT / "bin" / "tg")

sys.path.insert(0, str(ROOT))
import the_grid.cli as _cli_mod
from tests.fake_store import FakeStore

# Point every subprocess at a config that does NOT exist, so the suite reads
# config-absent DEFAULTS and never touches the real ~/.config/the-grid/config.
# Config-specific tests override GRID_CONFIG (per-test temp file, or by setting
# os.environ["GRID_CONFIG"] in setUp and restoring _ABSENT_CONFIG in tearDown).
_ABSENT_CONFIG = os.path.join(tempfile.mkdtemp(), "absent-config")
os.environ["GRID_CONFIG"] = _ABSENT_CONFIG


def run_tg(*args, root=None, config=None):
    env = dict(os.environ)
    if root:
        env["GRID_ROOT_OVERRIDE"] = root
    if config:
        env["GRID_CONFIG"] = config
    return subprocess.run([sys.executable, TG, *args], capture_output=True, text=True, env=env)


def write_config(projects=None, specs=None):
    """Write a temp grid config (the parts given) and return its path."""
    p = os.path.join(tempfile.mkdtemp(), "config")
    lines = []
    if projects is not None:
        lines.append("projects: %s" % projects)
    if specs is not None:
        lines.append("specs: %s" % specs)
    Path(p).write_text("".join(l + "\n" for l in lines))
    return p


_STORE_TEMPLATE = None


def _store_template():
    """A bd store inited once per run (git + bd init). new_store copies it - a
    filesystem copy is far cheaper than re-running bd/Dolt init for every test."""
    global _STORE_TEMPLATE
    if _STORE_TEMPLATE is None:
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(
            ["bd", "init", "--skip-agents", "--skip-hooks", "--non-interactive", "--quiet"],
            cwd=d, check=True,
        )
        _STORE_TEMPLATE = d
    return _STORE_TEMPLATE


def new_store():
    d = tempfile.mkdtemp()
    shutil.copytree(_store_template(), d, dirs_exist_ok=True)
    return d


def bd_in(root, *a):
    return subprocess.run(["bd", "-C", root, *a], capture_output=True, text=True, check=True).stdout


def git_in(root, *a):
    return subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, check=True)


def make_repo(parent, name):
    """A git repo `name` under `parent` with an `origin` whose `main` branch exists,
    so `git worktree add ... origin/main` resolves. Returns its path."""
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


def new_store_with_origin():
    """A grid store (the engine) that is a git repo with an `origin`/`main`, sitting
    under a parent dir so a test can point `projects` at that parent and have the
    engine's own basename resolve back to the store (the self-repo worktree)."""
    parent = tempfile.mkdtemp()
    d = make_repo(parent, "engine")
    shutil.copytree(os.path.join(_store_template(), ".beads"),
                    os.path.join(d, ".beads"), dirs_exist_ok=True)
    return d


_AGENT_SPECS = {
    "coder": ("sonnet", "build", {"done": "review"}),
    "reviewer": ("opus", "review", {"done": "open-pr", "rejected": "build"}),
    "pr-watcher": ("sonnet", "open-pr", {"done": "ready-merge", "ci-failed": "build"}),
    "driver": ("opus", None, None),
}


def write_steps(root, roles=("coder", "reviewer", "pr-watcher", "driver")):
    """Write the standard pipeline agents (routing only, no artifact contracts)."""
    adir = Path(root) / "steps"
    adir.mkdir(exist_ok=True)
    for r in roles:
        model, step, routes = _AGENT_SPECS[r]
        fm = ["---", "model: %s" % model]
        if step:
            fm.append("step: %s" % step)
        if routes:
            fm.append("routes:")
            fm += ["  %s: %s" % (o, n) for o, n in routes.items()]
        fm += ["---", "# %s" % r, "stub"]
        (adir / ("%s.md" % r)).write_text("\n".join(fm) + "\n")


_CONTRACT_SPECS = {
    "coder": dict(model="sonnet", step="build",
                  accepts={"spec": "required", "branch": "optional"},
                  produces={"branch": "required"}, routes={"done": "review"}),
    "reviewer": dict(model="opus", step="review",
                     accepts={"spec": "required", "branch": "required"}, produces={},
                     routes={"done": "open-pr", "rejected": "build"}),
    "pr-watcher": dict(model="sonnet", step="open-pr", accepts={"branch": "required"},
                       produces={"pr": "required"},
                       routes={"done": "ready-merge", "ci-failed": "build"}),
}


def write_contract_steps(root, specs=None):
    """Write agents that declare accepts/produces artifact contracts."""
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


def call(fn, *args):
    """Run a cmd_* in-process; return (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


def _fake_setUp(test, *, steps=False, contract_steps=False):
    """Common setUp for FakeStore-based tests: temp root, injected store, cleanup."""
    test.root = tempfile.mkdtemp()
    os.environ["GRID_ROOT_OVERRIDE"] = test.root
    if steps:
        write_steps(test.root)
    if contract_steps:
        write_contract_steps(test.root)
    test.store = FakeStore()
    test._orig = _cli_mod._store
    _cli_mod.set_store(test.store)
    test.addCleanup(lambda: _cli_mod.set_store(test._orig))
    test.addCleanup(lambda: os.environ.pop("GRID_ROOT_OVERRIDE", None))


class TestSkeleton(unittest.TestCase):
    def test_help_lists_subcommands(self):
        r = run_tg("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for verb in ("status", "claim", "done", "block", "run", "sweep"):
            self.assertIn(verb, r.stdout)

    def test_unknown_subcommand_exits_2(self):
        r = run_tg("wibble")
        self.assertEqual(r.returncode, 2)

    def test_help_is_grouped_and_described(self):
        r = run_tg("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("See what's happening", r.stdout)   # a group header
        self.assertIn("Start working", r.stdout)
        # a command must carry a real description, not just its name
        for line in r.stdout.splitlines():
            if line.strip().startswith("status "):
                self.assertGreater(len(line.split()), 3)
                break
        else:
            self.fail("status command not listed with a description")


class TestModel(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_task_mapping_and_status(self):
        bid = self.store.create_task("build: thing", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_show, bid)
        self.assertEqual(rc, 0, err)
        t = json.loads(out)
        self.assertEqual(t["role"], "coder")
        self.assertEqual(t["step"], "build")
        self.assertEqual(t["type"], "task")
        self.assertEqual(t["status"], "ready")

    def test_status_buckets_json(self):
        h = self.store.create_task("spec: x", step="spec", role="human")
        c = self.store.create_task("build: y", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_status, "--json")
        self.assertEqual(rc, 0, err)
        s = json.loads(out)
        self.assertIn(h, [t["id"] for t in s["mine"]])
        self.assertIn(c, [t["id"] for t in s["queue"]])


class TestClaim(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_claim_returns_and_marks_in_progress(self):
        c = self.store.create_task("build: y", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(rc, 0, err)
        t = json.loads(out)
        self.assertEqual(t["id"], c)
        self.assertEqual(t["status"], "in-progress")
        rc2, out2, _ = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(out2.strip(), "")

    def test_claim_ignores_human(self):
        self.store.create_task("spec: x", step="spec", role="human")
        rc, out, _ = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(out.strip(), "")

    def test_claim_assigns_worker_spawnid(self):
        b = self.store.create_task("build: y", step="build", role="coder")
        old = os.environ.get("GRID_SPAWNID")
        os.environ["GRID_SPAWNID"] = "spawn-xyz"
        try:
            call(_cli_mod.cmd_claim, "coder")
        finally:
            if old is None:
                os.environ.pop("GRID_SPAWNID", None)
            else:
                os.environ["GRID_SPAWNID"] = old
        self.assertEqual(self.store._beads[b].get("assignee"), "spawn-xyz")


class TestFlow(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_advance_creates_next_step(self):
        b = self.store.create_task("build: t", step="build", role="coder")
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
        self.store.create_task("build: t", step="build", role="coder")
        rc, out, _ = call(_cli_mod.cmd_ready_roles)
        self.assertIn("coder", out.split())


class TestDoneBlock(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_done_closes_and_advances(self):
        b = self.store.create_task("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "done")
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.strip())
        self.assertEqual(self.store._beads[b]["status"], "closed")

    def test_done_unknown_outcome_errors_without_closing(self):
        b = self.store.create_task("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "banana")
        self.assertEqual(rc, 1)
        self.assertEqual(self.store._beads[b]["status"], "open")

    def test_block_writes_metadata_and_routes_human(self):
        b = self.store.create_task("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_block, b, "--branch", "grid/x", "--needs", "confirm aud")
        self.assertEqual(rc, 0, err)
        bead = self.store._beads[b]
        self.assertEqual(bead["metadata"]["branch"], "grid/x")
        self.assertEqual(bead["metadata"]["needs"], "confirm aud")
        self.assertIn("for:human", bead["labels"])
        self.assertNotIn("for:coder", bead["labels"])

    def test_block_clears_assignee_and_surfaces_in_inbox(self):
        # A claimed task (assignee set) that gets blocked must clear the assignee,
        # else it stays "in-progress" and hides in `tg active` instead of `tg inbox`.
        b = self.store.create_task("build: t", step="build", role="coder")
        self.store.claim_ready("coder")
        rc, out, err = call(_cli_mod.cmd_block, b, "--needs", "rebase first")
        self.assertEqual(rc, 0, err)
        bead = self.store._beads[b]
        self.assertIn(bead.get("assignee"), (None, ""))
        rc2, inbox_out, _ = call(_cli_mod.cmd_inbox)
        self.assertIn(b, inbox_out)

    def test_done_note_forwards_to_next_task(self):
        b = self.store.create_task("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "done", "--note", "fix the coverage")
        self.assertEqual(rc, 0, err)
        new = out.strip()
        self.assertTrue(new)
        notes = self.store.get_task(new).get("notes") or ""
        self.assertIn("from build (done):", notes)
        self.assertIn("fix the coverage", notes)
        rc2, shown_out, _ = call(_cli_mod.cmd_show, new)
        shown = json.loads(shown_out)
        self.assertIn("fix the coverage", shown.get("notes") or "")

    def test_done_without_note_unchanged(self):
        b = self.store.create_task("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "done")
        self.assertEqual(rc, 0, err)
        new = out.strip()
        self.assertTrue(new)
        self.assertNotIn("from build", self.store.get_task(new).get("notes") or "")


class TestSweep(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)
        (Path(self.root) / "logs").mkdir(exist_ok=True)

    def test_sweep_releases_orphaned_claim(self):
        b = self.store.create_task("build: t", step="build", role="coder")
        self.store.claim_ready("coder")  # sets status="in_progress", assignee="coder"
        rc, out, err = call(_cli_mod.cmd_sweep)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store._beads[b]["status"], "open")
        self.assertIn(self.store._beads[b].get("assignee"), (None, ""))

    def test_sweep_keeps_task_of_live_worker_before_stamp(self):
        # Reproduces the double-claim TOCTOU: a worker has claimed the task
        # (assignee = its spawnid) but has not yet stamped its registry bead.
        # Sweep must NOT reclaim it - the owning worker is alive.
        b = self.store.create_task("build: t", step="build", role="coder")
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(
            [{"spawnid": "S", "role": "coder", "pid": os.getpid(), "log": "x", "bead": None}]))
        self.store.assign(b, "S")
        self.store.update_status(b, "in_progress")
        rc, out, err = call(_cli_mod.cmd_sweep)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store._beads[b]["status"], "in_progress")
        self.assertEqual(self.store._beads[b].get("assignee"), "S")

    def test_sweep_reclaims_dead_worker_claim(self):
        dead = subprocess.Popen(["true"]); dead.wait()
        b = self.store.create_task("build: t", step="build", role="coder")
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(
            [{"spawnid": "D", "role": "coder", "pid": dead.pid, "log": "x", "bead": b}]))
        self.store.assign(b, "D")
        self.store.update_status(b, "in_progress")
        rc, out, err = call(_cli_mod.cmd_sweep)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store._beads[b]["status"], "open")


class TestSpawn(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        for d in ("steps", "logs"):
            (Path(self.root) / d).mkdir(exist_ok=True)
        for r in ("coder", "reviewer", "pr-watcher"):
            (Path(self.root) / "steps" / ("%s.md" % r)).write_text(
                "---\nmodel: sonnet\n---\nstub %s" % r)

    def test_spawn_records_worker_and_log(self):
        env = dict(os.environ, GRID_ROOT_OVERRIDE=self.root, GRID_SPAWN_CMD="echo started >> {log}")
        r = subprocess.run([sys.executable, TG, "spawn", "coder"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0]["role"], "coder")
        self.assertTrue(os.path.exists(workers[0]["log"]))

    def test_ps_lists_worker(self):
        env = dict(os.environ, GRID_ROOT_OVERRIDE=self.root, GRID_SPAWN_CMD="sleep 0")
        subprocess.run([sys.executable, TG, "spawn", "coder"], env=env, capture_output=True)
        r = subprocess.run([sys.executable, TG, "ps", "--json"], capture_output=True, text=True, env=env)
        ps = json.loads(r.stdout)
        self.assertEqual(ps[0]["role"], "coder")


class TestRun(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        for d in ("steps", "logs", "flows"):
            (Path(self.root) / d).mkdir(exist_ok=True)
        for r in ("coder", "reviewer", "pr-watcher"):
            (Path(self.root) / "steps" / ("%s.md" % r)).write_text(
                "---\nmodel: sonnet\n---\nstub %s" % r)

    def test_run_once_spawns_for_ready_role(self):
        bd_in(self.root, "create", "build: t", "-t", "task", "-l", "for:coder,step:build", "--json")
        env = dict(os.environ, GRID_ROOT_OVERRIDE=self.root, GRID_SPAWN_CMD="echo x >> {log}")
        r = subprocess.run([sys.executable, TG, "run", "--once"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertTrue(any(w["role"] == "coder" for w in workers))

    def test_queue_lists_ready(self):
        c = json.loads(bd_in(self.root, "create", "build: y", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("queue", "5", root=self.root)
        self.assertIn(c, r.stdout)

    def _run_once(self):
        env = dict(os.environ, GRID_ROOT_OVERRIDE=self.root, GRID_SPAWN_CMD="echo x >> {log}")
        return subprocess.run([sys.executable, TG, "run", "--once"], capture_output=True, text=True, env=env)

    def test_run_skips_role_with_inflight_worker(self):
        # A coder is already booting (alive, claimed nothing yet -> bead None) recently.
        bd_in(self.root, "create", "build: t", "-t", "task", "-l", "for:coder,step:build", "--json")
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(
            [{"spawnid": "boot", "role": "coder", "pid": os.getpid(), "log": "x",
              "bead": None, "started": time.time()}]))
        r = self._run_once()
        self.assertEqual(r.returncode, 0, r.stderr)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertEqual(len(workers), 1)  # no second coder spawned

    def test_run_spawns_when_inflight_worker_is_stale(self):
        # A worker stuck booting far longer than the max boot age must not block forever.
        bd_in(self.root, "create", "build: t", "-t", "task", "-l", "for:coder,step:build", "--json")
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(
            [{"spawnid": "stuck", "role": "coder", "pid": os.getpid(), "log": "x",
              "bead": None, "started": time.time() - 9999}]))
        r = self._run_once()
        self.assertEqual(r.returncode, 0, r.stderr)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertEqual(len(workers), 2)  # stale boot no longer blocks the role

    def test_run_spawns_when_prior_worker_already_claimed(self):
        bd_in(self.root, "create", "build: t", "-t", "task", "-l", "for:coder,step:build", "--json")
        # prior coder already claimed something (bead set) -> not inflight
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(
            [{"spawnid": "old", "role": "coder", "pid": os.getpid(), "log": "x", "bead": "other-1"}]))
        r = self._run_once()
        self.assertEqual(r.returncode, 0, r.stderr)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertEqual(len(workers), 2)  # a fresh coder spawned for the ready task

    def test_run_pool_fills_up_to_max_agents(self):
        # 7 build + 3 review ready; the default pool cap of 4 spawns 4 workers in
        # one tick, drawn across roles from the ready queue (not one per role).
        for i in range(7):
            bd_in(self.root, "create", "build: %d" % i, "-t", "task",
                  "-l", "for:coder,step:build", "--json")
        for i in range(3):
            bd_in(self.root, "create", "review: %d" % i, "-t", "task",
                  "-l", "for:reviewer,step:review", "--json")
        r = self._run_once()
        self.assertEqual(r.returncode, 0, r.stderr)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertEqual(len(workers), 4)

    def test_run_pool_respects_max_agents_env(self):
        for i in range(5):
            bd_in(self.root, "create", "build: %d" % i, "-t", "task",
                  "-l", "for:coder,step:build", "--json")
        env = dict(os.environ, GRID_ROOT_OVERRIDE=self.root,
                   GRID_SPAWN_CMD="echo x >> {log}", GRID_MAX_AGENTS="2")
        r = subprocess.run([sys.executable, TG, "run", "--once"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertEqual(len(workers), 2)


class TestAdd(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_add_creates_standalone_human_task(self):
        rc, out, err = call(_cli_mod.cmd_add, "look at X later")
        self.assertEqual(rc, 0, err)
        new = out.strip()
        self.assertTrue(new)
        rc2, out2, _ = call(_cli_mod.cmd_show, new)
        t = json.loads(out2)
        self.assertEqual(t["role"], "human")
        self.assertEqual(t["status"], "needs-human")
        self.assertIsNone(t["step"])
        self.assertEqual(t["title"], "look at X later")

    def test_add_shows_in_mine_not_queue(self):
        call(_cli_mod.cmd_add, "remind me")
        rc, mine_out, _ = call(_cli_mod.cmd_mine)
        self.assertIn("remind me", mine_out)
        # standalone human task must NOT be claimable by an agent
        rc2, out2, _ = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(out2.strip(), "")


class TestArtifacts(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self._orig = _cli_mod._store
        _cli_mod.set_store(self.store)
        self.addCleanup(lambda: _cli_mod.set_store(self._orig))

    def test_add_and_read_artifacts_append(self):
        sid = self.store.create_story("story s")
        self.store.add_artifact(sid, "spec", "specs/X.md")
        self.store.add_artifact(sid, "pr", "https://gh/9", "PR 9")
        arts = self.store.story_artifacts(sid)
        self.assertEqual(len(arts), 2)
        self.assertEqual(arts[0]["type"], "spec")
        self.assertEqual(arts[1]["type"], "pr")
        self.assertEqual(arts[1]["label"], "PR 9")


class TestCompositionRoot(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self._orig = _cli_mod._store
        _cli_mod.set_store(self.store)
        self.addCleanup(lambda: _cli_mod.set_store(self._orig))

    def test_cmd_status_in_process_with_injected_store(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = _cli_mod.cmd_status(["--json"])
        self.assertEqual(ret, 0)
        s = json.loads(buf.getvalue())
        self.assertIn("mine", s)

    def test_store_is_replaced_and_restored(self):
        self.assertIs(_cli_mod._store, self.store)
        _cli_mod.set_store(self._orig)
        self.assertIs(_cli_mod._store, self._orig)
        _cli_mod.set_store(self.store)


class TestLink(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_link_appends_artifact(self):
        sid = self.store.create_story("story s")
        rc, out, err = call(_cli_mod.cmd_link, sid, "pr", "https://gh/9", "--label", "PR 9")
        self.assertEqual(rc, 0, err)
        arts = self.store.story_artifacts(sid)
        self.assertEqual(arts[0]["type"], "pr")
        self.assertEqual(arts[0]["value"], "https://gh/9")
        self.assertEqual(arts[0]["label"], "PR 9")


class TestModelV2(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def test_task_exposes_type_parent_and_parent_artifacts(self):
        epic = self.store.create_story("epic e")
        story = self.store.create_story("story s", epic=epic)
        self.store.update_metadata(story, {"artifacts": [{"type": "spec", "value": "specs/X.md"}]})
        task = self.store.create_task("build: b", step="build", role="coder", parent=story)
        rc, out, _ = call(_cli_mod.cmd_show, task)
        v = json.loads(out)
        self.assertEqual(v["type"], "task")
        self.assertEqual(v["parent"], story)
        self.assertEqual(v["story_artifacts"][0]["value"], "specs/X.md")


class TestFileStory(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_file_creates_story_with_spec_and_build_task(self):
        rc, out, err = call(_cli_mod.cmd_file, "specs/HSS-435.md", "--step", "build")
        self.assertEqual(rc, 0, err)
        sid = out.strip()
        self.assertTrue(sid)
        story_bead = self.store._beads[sid]
        self.assertEqual(story_bead["issue_type"], "story")
        self.assertEqual(story_bead["metadata"]["artifacts"][0]["value"], "specs/HSS-435.md")
        kids = self.store.children(sid)
        self.assertEqual(len(kids), 1)
        rc2, out2, _ = call(_cli_mod.cmd_show, kids[0]["id"])
        self.assertEqual(json.loads(out2)["step"], "build")

    def test_advance_parents_next_task_to_same_story(self):
        rc, out, _ = call(_cli_mod.cmd_file, "specs/X.md", "--step", "build")
        sid = out.strip()
        build = self.store.children(sid)[0]["id"]
        self.store.close(build, "done")
        rc2, out2, err2 = call(_cli_mod.cmd_advance, build, "done")
        new = out2.strip()
        rc3, out3, _ = call(_cli_mod.cmd_show, new)
        nt = json.loads(out3)
        self.assertEqual(nt["parent"], sid)
        self.assertEqual(nt["step"], "review")
        self.assertEqual(nt["story_artifacts"][0]["value"], "specs/X.md")


class TestFileBlockedBy(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_blocked_by_creates_dependency_on_first_task(self):
        gate = self.store.create_task("review-plan: foo", step="review-plan", role="human")
        rc, out, err = call(_cli_mod.cmd_file, "specs/X.md", "--step", "build",
                            "--blocked-by", gate)
        self.assertEqual(rc, 0, err)
        sid = out.strip()
        self.assertTrue(sid)
        task_id = self.store.children(sid)[0]["id"]
        self.assertIn(gate, self.store._deps.get(task_id, set()))

    def test_blocked_task_not_claimable_until_gate_closes(self):
        gate = self.store.create_task("review-plan: foo", step="review-plan", role="human")
        call(_cli_mod.cmd_file, "specs/X.md", "--step", "build", "--blocked-by", gate)
        rc, out, _ = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(out.strip(), "")  # not claimable while gate is open
        self.store.close(gate, "approved")
        rc2, out2, _ = call(_cli_mod.cmd_claim, "coder")
        self.assertTrue(out2.strip())  # now claimable

    def test_multiple_blocked_by_ids(self):
        gate1 = self.store.create_task("gate1", labels=["for:human"])
        gate2 = self.store.create_task("gate2", labels=["for:human"])
        rc, out, _ = call(_cli_mod.cmd_file, "specs/X.md", "--step", "build",
                          "--blocked-by", gate1, "--blocked-by", gate2)
        sid = out.strip()
        task_id = self.store.children(sid)[0]["id"]
        blocker_ids = self.store._deps.get(task_id, set())
        self.assertIn(gate1, blocker_ids)
        self.assertIn(gate2, blocker_ids)


class TestClaimArtifacts(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_claim_surfaces_story_artifacts(self):
        call(_cli_mod.cmd_file, "specs/Y.md", "--step", "build")
        rc, out, err = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(rc, 0, err)
        t = json.loads(out)
        self.assertEqual(t["story_artifacts"][0]["value"], "specs/Y.md")

    def test_set_is_gone(self):
        r = run_tg("set", "x", "--pr", "y")
        self.assertEqual(r.returncode, 2)


class TestTrace(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_trace_shows_story_artifacts_and_tasks(self):
        rc, out, err = call(_cli_mod.cmd_file, "specs/Z.md", "--step", "build")
        sid = out.strip()
        rc2, out2, err2 = call(_cli_mod.cmd_trace, sid, "--json")
        self.assertEqual(rc2, 0, err2)
        tr = json.loads(out2)
        self.assertEqual(tr["story"]["id"], sid)
        self.assertEqual(tr["artifacts"][0]["value"], "specs/Z.md")
        self.assertEqual(len(tr["tasks"]), 1)
        self.assertEqual(tr["tasks"][0]["step"], "build")


class TestAgentFrontmatter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()  # parse_step reads step files - no bd needed
        (Path(self.root) / "steps").mkdir(exist_ok=True)
        (Path(self.root) / "steps" / "coder.md").write_text(
            "---\nmodel: sonnet\n---\n# Coder\n\nDo the thing.\n")
        (Path(self.root) / "logs").mkdir(exist_ok=True)

    def _tg(self):
        import importlib.util
        from importlib.machinery import SourceFileLoader
        os.environ["GRID_ROOT_OVERRIDE"] = self.root
        loader = SourceFileLoader("tgmod_fm", TG)
        spec = importlib.util.spec_from_loader("tgmod_fm", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def test_parse_step_extracts_model_and_strips_frontmatter(self):
        tg = self._tg()
        a = tg.parse_step("coder")
        self.assertEqual(a["meta"]["model"], "sonnet")
        self.assertTrue(a["body"].startswith("# Coder"))
        self.assertNotIn("model:", a["body"])

    def test_parse_step_reads_nested_routes(self):
        (Path(self.root) / "steps" / "reviewer.md").write_text(
            "---\nmodel: opus\nstep: review\nroutes:\n  done: open-pr\n"
            "  rejected: build\n---\n# Reviewer\n")
        tg = self._tg()
        a = tg.parse_step("reviewer")
        self.assertEqual(a["meta"]["step"], "review")
        self.assertEqual(a["meta"]["routes"], {"done": "open-pr", "rejected": "build"})
        self.assertTrue(a["body"].startswith("# Reviewer"))


class TestFlowFromAgents(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()  # tests pure flow_next over step files - no bd needed
        write_steps(self.root)

    def _tg(self):
        import importlib.util
        from importlib.machinery import SourceFileLoader
        os.environ["GRID_ROOT_OVERRIDE"] = self.root
        loader = SourceFileLoader("tgmod_flow", TG)
        spec = importlib.util.spec_from_loader("tgmod_flow", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def test_flow_next_derives_role_from_owner(self):
        tg = self._tg()
        self.assertEqual(tg.flow_next("build", "done"), ("review", "reviewer"))
        self.assertEqual(tg.flow_next("review", "rejected"), ("build", "coder"))

    def test_flow_next_unowned_target_routes_to_human(self):
        tg = self._tg()
        self.assertEqual(tg.flow_next("open-pr", "done"), ("ready-merge", "human"))

    def test_flow_next_unknown_outcome_is_none(self):
        tg = self._tg()
        self.assertIsNone(tg.flow_next("build", "banana"))

    def test_flow_command_lists_steps_and_human_terminal(self):
        r = run_tg("flow", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("build", r.stdout)
        self.assertIn("review", r.stdout)
        self.assertIn("human", r.stdout)


class TestFileStep(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_steps(self.root)

    def test_file_requires_step(self):
        r = run_tg("file", "specs/X.md", root=self.root)
        self.assertEqual(r.returncode, 2)

    def test_file_rejects_unknown_step(self):
        r = run_tg("file", "specs/X.md", "--step", "bogus", root=self.root)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("bogus", r.stderr)

    def test_file_starts_at_given_step(self):
        sid = run_tg("file", "specs/X.md", "--step", "build", root=self.root).stdout.strip()
        kids = json.loads(bd_in(self.root, "children", sid, "--json"))
        kid = json.loads(run_tg("show", kids[0]["id"], root=self.root).stdout)
        self.assertEqual(kid["step"], "build")
        self.assertEqual(kid["role"], "coder")

    def test_spawn_uses_frontmatter_model(self):
        env = dict(os.environ, GRID_ROOT_OVERRIDE=self.root, GRID_SPAWN_CMD="echo x >> {log}")
        r = subprocess.run([sys.executable, TG, "spawn", "coder"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_spawn_refuses_when_model_missing(self):
        (Path(self.root) / "steps" / "reviewer.md").write_text("no frontmatter here")
        env = dict(os.environ, GRID_ROOT_OVERRIDE=self.root, GRID_SPAWN_CMD="echo x >> {log}")
        r = subprocess.run([sys.executable, TG, "spawn", "reviewer"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("model", r.stderr)


class TestArtifactContracts(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, contract_steps=True)

    def test_claim_escalates_when_required_input_missing(self):
        b = self.store.create_task("build: x", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), "")  # not claimed
        bead = self.store._beads[b]
        self.assertIn("for:human", bead["labels"])
        self.assertNotIn("for:coder", bead["labels"])
        self.assertEqual(bead["status"], "open")

    def test_claim_proceeds_when_inputs_present(self):
        rc, out, err = call(_cli_mod.cmd_file, "specs/X.md", "--step", "build")
        sid = out.strip()
        rc2, out2, err2 = call(_cli_mod.cmd_claim, "coder")
        self.assertEqual(rc2, 0, err2)
        t = json.loads(out2)
        self.assertEqual(t["status"], "in-progress")
        self.assertEqual(t["parent"], sid)

    def test_done_refused_when_required_output_missing(self):
        rc, out, _ = call(_cli_mod.cmd_file, "specs/X.md", "--step", "build")
        sid = out.strip()
        task = self.store.children(sid)[0]["id"]
        rc2, out2, err2 = call(_cli_mod.cmd_done, task, "done")
        self.assertEqual(rc2, 1)
        self.assertIn("branch", err2)
        self.assertEqual(self.store._beads[task]["status"], "open")

    def test_done_succeeds_when_output_present(self):
        rc, out, _ = call(_cli_mod.cmd_file, "specs/X.md", "--step", "build")
        sid = out.strip()
        task = self.store.children(sid)[0]["id"]
        call(_cli_mod.cmd_link, sid, "branch", "grid/x")
        rc2, out2, err2 = call(_cli_mod.cmd_done, task, "done")
        self.assertEqual(rc2, 0, err2)
        self.assertEqual(self.store._beads[task]["status"], "closed")

    def test_file_rejects_non_entry_step(self):
        rc, out, err = call(_cli_mod.cmd_file, "specs/X.md", "--step", "review")
        self.assertEqual(rc, 1)
        self.assertIn("branch", err)

    def test_flow_reports_composition_ok(self):
        rc, out, err = call(_cli_mod.cmd_flow)
        self.assertEqual(rc, 0, err)
        self.assertIn("branch", out)  # produces shown

    def test_flow_flags_broken_composition(self):
        specs = {k: dict(v) for k, v in _CONTRACT_SPECS.items()}
        specs["reviewer"] = dict(specs["reviewer"],
                                 accepts={"spec": "required", "design": "required"})
        write_contract_steps(self.root, specs)
        rc, out, err = call(_cli_mod.cmd_flow)
        self.assertEqual(rc, 1)
        self.assertIn("design", err)


class TestPruneWorkers(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        (Path(self.root) / "logs").mkdir(exist_ok=True)
        self.wfile = Path(self.root) / "logs" / "workers.json"

    def _dead_pid(self):
        p = subprocess.Popen(["true"])
        p.wait()
        return p.pid

    def _write(self, workers):
        self.wfile.write_text(json.dumps(workers))

    def _sweep(self, history=None):
        env = dict(os.environ, GRID_ROOT_OVERRIDE=self.root)
        if history is not None:
            env["GRID_WORKER_HISTORY"] = str(history)
        return subprocess.run([sys.executable, TG, "sweep"], capture_output=True, text=True, env=env)

    def test_sweep_prunes_dead_keeps_live(self):
        dead = self._dead_pid()
        self._write([
            {"spawnid": "a", "role": "coder", "pid": os.getpid(), "log": "x", "bead": None},
            {"spawnid": "b", "role": "coder", "pid": dead, "log": "y", "bead": None},
        ])
        r = self._sweep(history=0)
        self.assertEqual(r.returncode, 0, r.stderr)
        ids = [w["spawnid"] for w in json.loads(self.wfile.read_text())]
        self.assertEqual(ids, ["a"])

    def test_sweep_keeps_recent_dead_for_log_lookup(self):
        dead = self._dead_pid()
        self._write([{"spawnid": "d%d" % i, "role": "coder", "pid": dead, "log": "l", "bead": None}
                     for i in range(3)])
        self._sweep(history=2)
        ids = [w["spawnid"] for w in json.loads(self.wfile.read_text())]
        self.assertEqual(ids, ["d1", "d2"])


class TestInitAndStoreGuard(unittest.TestCase):
    def _bare(self):
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        return d

    def _cfg(self, d):
        # init now seeds a config; keep it inside d so it can't pollute the suite.
        return os.path.join(d, "grid-config")

    def test_init_creates_store(self):
        d = self._bare()
        r = run_tg("init", root=d, config=self._cfg(d))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(d, ".beads")))

    def test_init_idempotent(self):
        d = self._bare()
        run_tg("init", root=d, config=self._cfg(d))
        r = run_tg("init", root=d, config=self._cfg(d))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_run_without_store_errors(self):
        d = self._bare()
        r = run_tg("run", "--once", root=d)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("init", r.stderr)

    def test_up_is_gone(self):
        r = run_tg("up")
        self.assertEqual(r.returncode, 2)


class TestContractsOptional(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)  # no requires/produces

    def test_done_without_contract_needs_no_artifacts(self):
        b = self.store.create_task("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_done, b, "done")
        self.assertEqual(rc, 0, err)


class TestWorktree(unittest.TestCase):
    def setUp(self):
        self.root = new_store_with_origin()
        write_steps(self.root)
        # projects -> the engine's parent so basename(root) resolves to the store;
        # specs -> the store so file's relative spec path resolves under it.
        os.environ["GRID_CONFIG"] = write_config(
            projects=os.path.dirname(self.root), specs=self.root)

    def tearDown(self):
        os.environ["GRID_CONFIG"] = _ABSENT_CONFIG

    def _branch_of(self, path):
        return git_in(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def _tg(self):
        import importlib.util
        from importlib.machinery import SourceFileLoader
        os.environ["GRID_ROOT_OVERRIDE"] = self.root
        loader = SourceFileLoader("tgmod_wt", TG)
        spec = importlib.util.spec_from_loader("tgmod_wt", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        mod.set_store(mod.BdStore())
        return mod

    def test_claim_returns_isolated_workspace(self):
        sid = run_tg("file", "specs/W.md", "--step", "build", root=self.root).stdout.strip()
        t = json.loads(run_tg("claim", "coder", root=self.root).stdout)
        ws = t["workspace"]
        self.assertTrue(os.path.isdir(ws))
        self.assertEqual(os.path.basename(ws), sid)
        self.assertEqual(os.path.dirname(ws), os.path.join(self.root, ".worktrees"))
        self.assertEqual(self._branch_of(ws), "feat/w")
        self.assertEqual(t["branch"], "feat/w")

    def test_claim_does_not_switch_root_branch(self):
        run_tg("file", "specs/W.md", "--step", "build", root=self.root)
        before = self._branch_of(self.root)
        run_tg("claim", "coder", root=self.root)
        self.assertEqual(self._branch_of(self.root), before)
        self.assertEqual(self._branch_of(self.root), "main")

    def test_worktree_reused_across_roles(self):
        sid = run_tg("file", "specs/W.md", "--step", "build", root=self.root).stdout.strip()
        ws1 = json.loads(run_tg("claim", "coder", root=self.root).stdout)["workspace"]
        build = json.loads(bd_in(self.root, "children", sid, "--json"))[0]["id"]
        run_tg("done", build, "done", root=self.root)
        ws2 = json.loads(run_tg("claim", "reviewer", root=self.root).stdout)["workspace"]
        self.assertEqual(ws1, ws2)

    def test_branch_artifact_autolinked_on_claim(self):
        sid = run_tg("file", "specs/W.md", "--step", "build", root=self.root).stdout.strip()
        run_tg("claim", "coder", root=self.root)
        arts = json.loads(bd_in(self.root, "show", sid, "--json"))[0]["metadata"]["artifacts"]
        branches = [a for a in arts if a["type"] == "branch"]
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["value"], "feat/w")

    def test_worktrees_dir_gitignored(self):
        run_tg("file", "specs/W.md", "--step", "build", root=self.root)
        run_tg("claim", "coder", root=self.root)
        gi = (Path(self.root) / ".gitignore").read_text().splitlines()
        self.assertIn(".worktrees/", [l.strip() for l in gi])

    def test_reclaim_reuses_existing_branch(self):
        sid = run_tg("file", "specs/W.md", "--step", "build", root=self.root).stdout.strip()
        tg = self._tg()
        ws = tg.ensure_worktree(sid)
        (Path(ws) / "f.txt").write_text("x")
        git_in(ws, "add", ".")
        git_in(ws, "commit", "-q", "-m", "w")
        git_in(self.root, "worktree", "remove", "--force", ws)
        self.assertFalse(os.path.isdir(ws))
        ws2 = tg.ensure_worktree(sid)
        self.assertEqual(ws, ws2)
        self.assertEqual(self._branch_of(ws2), "feat/w")
        self.assertTrue(os.path.isfile(os.path.join(ws2, "f.txt")))


class TestWorktreeNoOrigin(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_steps(self.root)

    def test_claim_omits_workspace_without_origin(self):
        bd_in(self.root, "create", "build: t", "-t", "task",
              "-l", "for:coder,step:build", "--json")
        t = json.loads(run_tg("claim", "coder", root=self.root).stdout)
        self.assertEqual(t["status"], "in-progress")
        self.assertNotIn("workspace", t)


class TestNamedRepo(unittest.TestCase):
    def setUp(self):
        self.engine = new_store_with_origin()  # engine repo under a projects parent
        write_steps(self.engine)
        self.projects = os.path.dirname(self.engine)
        self.app = make_repo(self.projects, "app")  # a sibling repo, referenced by name
        os.environ["GRID_CONFIG"] = write_config(projects=self.projects, specs=self.engine)

    def tearDown(self):
        os.environ["GRID_CONFIG"] = _ABSENT_CONFIG

    def _has_branch(self, repo, branch):
        return subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet",
                               "refs/heads/" + branch], capture_output=True).returncode == 0

    def _claim(self, repo=None):
        args = ["file", "specs/X.md", "--step", "build"]
        if repo:
            args += ["--repo", repo]
        run_tg(*args, root=self.engine)
        r = run_tg("claim", "coder", root=self.engine)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_named_repo_worktree_created_engine_untouched(self):
        view = self._claim("app")
        branch = "feat/x"
        self.assertEqual(view["workspace"],
                         os.path.join(self.engine, ".worktrees", view["parent"]))
        self.assertTrue(os.path.isdir(view["workspace"]))
        self.assertTrue(self._has_branch(self.app, branch))      # branch lives in the named repo
        self.assertFalse(self._has_branch(self.engine, branch))  # engine repo untouched

    def test_default_repo_targets_self(self):
        view = self._claim()  # no --repo
        branch = "feat/x"
        self.assertTrue(os.path.isdir(view["workspace"]))
        self.assertTrue(self._has_branch(self.engine, branch))  # self repo got the branch
        self.assertFalse(self._has_branch(self.app, branch))

    def test_claim_includes_absolute_spec_path(self):
        view = self._claim("app")
        self.assertTrue(os.path.isabs(view["spec_path"]))
        self.assertTrue(view["spec_path"].endswith("specs/X.md"))
        self.assertTrue(view["spec_path"].startswith(self.engine))  # default specs_root = engine

    def test_file_stores_single_repo_artifact(self):
        sid = run_tg("file", "specs/X.md", "--step", "build", "--repo", "app",
                     root=self.engine).stdout.strip()
        arts = json.loads(bd_in(self.engine, "show", sid, "--json"))[0]["metadata"]["artifacts"]
        repos = [a["value"] for a in arts if a["type"] == "repo"]
        self.assertEqual(repos, ["app"])

    def test_file_rejects_unknown_repo(self):
        before = json.loads(bd_in(self.engine, "list", "--json"))
        r = run_tg("file", "specs/X.md", "--step", "build", "--repo", "does-not-exist",
                   root=self.engine)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does-not-exist", r.stderr)
        after = json.loads(bd_in(self.engine, "list", "--json"))
        self.assertEqual(len(before), len(after))


class TestUnblock(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self, steps=True)

    def test_unblock_returns_blocked_task_to_agent_role(self):
        b = self.store.create_task("build: t", step="build", role="coder")
        self.store.claim_ready("coder")  # claim it
        call(_cli_mod.cmd_block, b, "--needs", "rebase first")
        rc, out, err = call(_cli_mod.cmd_unblock, b)
        self.assertEqual(rc, 0, err)
        bead = self.store._beads[b]
        self.assertIn("for:coder", bead["labels"])
        self.assertNotIn("for:human", bead["labels"])
        self.assertEqual(bead["status"], "open")
        self.assertIn(bead.get("assignee"), (None, ""))
        t = self.store.get_task(b)
        self.assertEqual(t["status"], "ready")
        self.assertEqual(t["role"], "coder")

    def test_unblock_refuses_human_step(self):
        (Path(self.root) / "steps" / "ready-merge.md").write_text(
            "---\nstep: ready-merge\nroutes:\n  merged: cleanup\n---\n# ready-merge\n")
        b = self.store.create_task("ready-merge: t", step="ready-merge", role="human")
        rc, out, err = call(_cli_mod.cmd_unblock, b)
        self.assertEqual(rc, 1)
        self.assertIn("ready-merge", err)


class TestClose(unittest.TestCase):
    def setUp(self):
        self.root = new_store_with_origin()
        write_steps(self.root)
        os.environ["GRID_CONFIG"] = write_config(
            projects=os.path.dirname(self.root), specs=self.root)

    def tearDown(self):
        os.environ["GRID_CONFIG"] = _ABSENT_CONFIG

    def _has_branch(self, repo, branch):
        return subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet",
                               "refs/heads/" + branch], capture_output=True).returncode == 0

    def test_close_closes_story_and_tasks_and_removes_worktree(self):
        sid = run_tg("file", "specs/W.md", "--step", "build", root=self.root).stdout.strip()
        ws = json.loads(run_tg("claim", "coder", root=self.root).stdout)["workspace"]
        self.assertTrue(os.path.isdir(ws))
        build = json.loads(bd_in(self.root, "children", sid, "--json"))[0]["id"]
        r = run_tg("close", sid, "merged", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(bd_in(self.root, "show", sid, "--json"))[0]["status"], "closed")
        self.assertEqual(json.loads(bd_in(self.root, "show", build, "--json"))[0]["status"], "closed")
        self.assertFalse(os.path.isdir(ws))
        self.assertFalse(self._has_branch(self.root, "feat/w"))


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()  # config is filesystem; spec_path test makes its own store
        self.dir = tempfile.mkdtemp()
        self.cfg = os.path.join(self.dir, "config")

    def test_config_prints_path_and_defaults(self):
        r = run_tg("config", root=self.root, config=self.cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(self.cfg, r.stdout)
        self.assertIn("(using defaults)", r.stdout)
        self.assertIn("projects: %s" % os.path.expanduser("~/workspace/projects"), r.stdout)
        self.assertIn("specs: %s" % os.path.expanduser("~/workspace/specs"), r.stdout)

    def test_init_seeds_config_when_absent_and_is_idempotent(self):
        self.assertFalse(os.path.exists(self.cfg))
        r = run_tg("init", root=self.root, config=self.cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("created", r.stdout)
        self.assertTrue(os.path.exists(self.cfg))
        self.assertIn("~/workspace/projects", Path(self.cfg).read_text())
        r2 = run_tg("init", root=self.root, config=self.cfg)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("already exists", r2.stdout)

    def test_written_config_overrides_roots(self):
        proj = tempfile.mkdtemp()
        specs = tempfile.mkdtemp()
        Path(self.cfg).write_text("projects: %s\nspecs: %s\n" % (proj, specs))
        r = run_tg("config", root=self.root, config=self.cfg)
        self.assertIn("projects: %s" % proj, r.stdout)
        self.assertIn("specs: %s" % specs, r.stdout)

    def test_spec_path_resolves_against_configured_specs_root(self):
        root = new_store_with_origin()
        write_steps(root)
        specs = tempfile.mkdtemp()
        Path(self.cfg).write_text("specs: %s\n" % specs)
        run_tg("file", "specs/X.md", "--step", "build", root=root, config=self.cfg)
        view = json.loads(run_tg("claim", "coder", root=root, config=self.cfg).stdout)
        self.assertEqual(view["spec_path"], os.path.join(specs, "specs/X.md"))


class TestLogRender(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()  # cmd_logs reads log files only - no bd needed
        (Path(self.root) / "logs").mkdir(exist_ok=True)
        self.log = Path(self.root) / "logs" / "worker-coder-x.log"
        self.log.write_text("\n".join([
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Claiming the task."}]}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "tg claim coder"}}]}}),
            json.dumps({"type": "result", "result": "done; banner fixed"}),
        ]) + "\n")
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(
            [{"spawnid": "x", "role": "coder", "pid": os.getpid(),
              "log": str(self.log), "bead": None, "started": time.time()}]))

    def test_logs_renders_stream_json(self):
        r = run_tg("logs", "coder", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Claiming the task.", r.stdout)
        self.assertIn("$ tg claim coder", r.stdout)
        self.assertIn("done; banner fixed", r.stdout)
        self.assertNotIn('"type"', r.stdout)  # raw JSON is not shown


class TestMine(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.environ["GRID_ROOT_OVERRIDE"] = self.root
        adir = Path(self.root) / "steps"
        adir.mkdir(exist_ok=True)
        (adir / "coder.md").write_text(
            "---\nmodel: sonnet\nstep: build\nroutes:\n  done: review\n---\nstub")
        (adir / "ready-merge.md").write_text(
            "---\nstep: ready-merge\nroutes:\n  merged: cleanup\n  changes: build\n---\nstub")
        self.store = FakeStore()
        self._orig = _cli_mod._store
        _cli_mod.set_store(self.store)
        self.addCleanup(lambda: _cli_mod.set_store(self._orig))
        self.addCleanup(lambda: os.environ.pop("GRID_ROOT_OVERRIDE", None))

    def test_mine_tags_orders_and_shows_context(self):
        call(_cli_mod.cmd_add, "look at X")                                        # todo
        sid = self.store.create_story("feat")
        self.store.update_metadata(sid, {"artifacts": [{"type": "pr", "value": "http://pr/1"}]})
        self.store.create_task("merge: y", step="ready-merge", role="human", parent=sid)  # action
        b = self.store.create_task("build: z", step="build", role="human")
        self.store.update_metadata(b, {"needs": "rebase first"})                   # blocked
        _, out, _ = call(_cli_mod.cmd_mine)
        for tag in ("[blocked]", "[action]", "[todo]"):
            self.assertIn(tag, out)
        self.assertIn("merge: y", out)
        self.assertIn("look at X", out)
        self.assertLess(out.index("[blocked]"), out.index("[action]"))
        self.assertLess(out.index("[action]"), out.index("[todo]"))

    def test_mine_shows_plan_doc_for_gate_task(self):
        gate = self.store.create_task("review-plan: foo", step="ready-merge", role="human")
        self.store.update_metadata(gate, {"artifacts": [{"type": "plan-doc", "value": "/tmp/plan.md"}]})
        _, out, _ = call(_cli_mod.cmd_mine)
        self.assertIn("plan:/tmp/plan.md", out)

    def test_mine_emits_deprecation_warning(self):
        call(_cli_mod.cmd_add, "remind me")
        rc, out, err = call(_cli_mod.cmd_mine)
        self.assertIn("deprecated", err)
        self.assertIn("tg inbox", err)
        self.assertIn("tg backlog", err)

    def test_inbox_shows_action_and_blocked_only(self):
        call(_cli_mod.cmd_add, "a seed")                                           # todo
        self.store.create_task("merge: z", step="ready-merge", role="human")       # action
        self.store.create_task("build: q", step="build", role="human")             # blocked
        _, out, _ = call(_cli_mod.cmd_inbox)
        self.assertIn("[action]", out)
        self.assertIn("[blocked]", out)
        self.assertNotIn("[todo]", out)
        self.assertNotIn("a seed", out)

    def test_backlog_shows_todo_only(self):
        call(_cli_mod.cmd_add, "a seed")                                           # todo
        self.store.create_task("merge: z", step="ready-merge", role="human")       # action
        _, out, _ = call(_cli_mod.cmd_backlog)
        self.assertIn("[todo]", out)
        self.assertIn("a seed", out)
        self.assertNotIn("[action]", out)

    def test_inbox_limit_n(self):
        self.store.create_task("merge: p", step="ready-merge", role="human")
        self.store.create_task("merge: q", step="ready-merge", role="human")
        self.store.create_task("merge: r", step="ready-merge", role="human")
        _, out, _ = call(_cli_mod.cmd_inbox, "1")
        self.assertEqual(len([l for l in out.splitlines() if l.strip()]), 1)

    def test_backlog_limit_n(self):
        call(_cli_mod.cmd_add, "seed one")
        call(_cli_mod.cmd_add, "seed two")
        call(_cli_mod.cmd_add, "seed three")
        _, out, _ = call(_cli_mod.cmd_backlog, "2")
        self.assertEqual(len([l for l in out.splitlines() if l.strip()]), 2)


class TestReflect(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def _file_story(self, spec_path=None):
        sid = self.store.create_story("feat")
        self.store.update_metadata(sid, {"artifacts": [{"type": "spec", "value": spec_path or "/tmp/no-spec.md"}]})
        tid = self.store.create_task("build: feat", step="build", role="coder", parent=sid)
        return sid, tid

    def test_reflect_stores_artifact_on_story(self):
        sid, tid = self._file_story()
        rc, out, err = call(_cli_mod.cmd_reflect, tid, "--used", "Summary,Scope", "--skipped", "Risks")
        self.assertEqual(rc, 0, err)
        self.assertIn("reflected", out)
        arts = self.store.story_artifacts(sid)
        refs = [a for a in arts if a["type"] == "reflection"]
        self.assertEqual(len(refs), 1)
        data = json.loads(refs[0]["value"])
        self.assertEqual(data["sections"]["Summary"], "used")
        self.assertEqual(data["sections"]["Scope"], "used")
        self.assertEqual(data["sections"]["Risks"], "skipped")
        self.assertEqual(data["task"], tid)

    def test_reflect_records_guess_missing_noise(self):
        sid, tid = self._file_story()
        rc, out, err = call(_cli_mod.cmd_reflect, tid,
                            "--guess", "Decisions",
                            "--missing", "acceptance criteria",
                            "--missing", "error cases",
                            "--noise", "Out of scope")
        self.assertEqual(rc, 0, err)
        arts = self.store.story_artifacts(sid)
        data = json.loads(next(a for a in arts if a["type"] == "reflection")["value"])
        self.assertEqual(data["sections"]["Decisions"], "guess")
        self.assertIn("acceptance criteria", data["missing"])
        self.assertIn("error cases", data["missing"])
        self.assertIn("Out of scope", data["noise"])

    def test_reflect_multiple_calls_append(self):
        sid, tid = self._file_story()
        call(_cli_mod.cmd_reflect, tid, "--used", "Summary")
        call(_cli_mod.cmd_reflect, tid, "--used", "Scope")
        arts = self.store.story_artifacts(sid)
        refs = [a for a in arts if a["type"] == "reflection"]
        self.assertEqual(len(refs), 2)

    def test_reflect_stamps_spec_hash(self):
        import tempfile as _tmpfile
        spec = _tmpfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
        spec.write("# spec\ncontent")
        spec.close()
        sid, tid = self._file_story(spec_path=spec.name)
        self.store.update_metadata(sid, {"artifacts": [{"type": "spec", "value": spec.name}]})
        call(_cli_mod.cmd_reflect, tid, "--used", "spec")
        arts = self.store.story_artifacts(sid)
        data = json.loads(next(a for a in arts if a["type"] == "reflection")["value"])
        self.assertNotEqual(data["spec_hash"], "unknown")
        self.assertEqual(len(data["spec_hash"]), 8)

    def test_reflect_no_sections_still_valid(self):
        sid, tid = self._file_story()
        rc, out, err = call(_cli_mod.cmd_reflect, tid)
        self.assertEqual(rc, 0, err)
        arts = self.store.story_artifacts(sid)
        data = json.loads(next(a for a in arts if a["type"] == "reflection")["value"])
        self.assertEqual(data["sections"], {})
        self.assertEqual(data["missing"], [])
        self.assertEqual(data["noise"], [])


class TestRetro(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def _make_epic_with_story(self, sid=None):
        epic = self.store.create_story("epic-1")
        if sid is None:
            sid = self.store.create_story("story-1", epic=epic)
        return epic, sid

    def test_retro_no_reflections(self):
        epic, _ = self._make_epic_with_story()
        rc, out, err = call(_cli_mod.cmd_retro, epic)
        self.assertEqual(rc, 0, err)
        self.assertIn("N=0", out)
        self.assertIn("no reflections yet", out)
        self.assertIn("Per-story signals", out)

    def test_retro_aggregates_section_counts(self):
        epic, sid = self._make_epic_with_story()
        tid = self.store.create_task("build: s", step="build", role="coder", parent=sid)
        call(_cli_mod.cmd_reflect, tid, "--used", "Summary,Scope", "--skipped", "Risks")
        rc, out, err = call(_cli_mod.cmd_retro, epic)
        self.assertEqual(rc, 0, err)
        self.assertIn("N=1", out)
        self.assertIn("Summary", out)
        self.assertIn("used=1", out)
        self.assertIn("Risks", out)
        self.assertIn("skipped=1", out)

    def test_retro_aggregates_missing_and_noise(self):
        epic, sid = self._make_epic_with_story()
        tid = self.store.create_task("build: s", step="build", role="coder", parent=sid)
        call(_cli_mod.cmd_reflect, tid, "--missing", "edge case coverage", "--noise", "Out of scope")
        rc, out, err = call(_cli_mod.cmd_retro, epic)
        self.assertIn("edge case coverage", out)
        self.assertIn("Out of scope", out)

    def test_retro_signals_review_rounds(self):
        epic, sid = self._make_epic_with_story()
        self.store.create_task("review: s", step="review", role="reviewer", parent=sid)
        rtid = self.store.create_task("review: s2", step="review", role="reviewer", parent=sid)
        self.store.close(rtid, "rejected")
        rc, out, err = call(_cli_mod.cmd_retro, epic)
        self.assertEqual(rc, 0, err)
        self.assertIn("rounds=1", out)

    def test_retro_signals_conflict(self):
        epic, sid = self._make_epic_with_story()
        pr_tid = self.store.create_task("open-pr: s", step="open-pr", role="pr-watcher", parent=sid)
        self.store.close(pr_tid, "conflict-rebase")
        rc, out, err = call(_cli_mod.cmd_retro, epic)
        self.assertEqual(rc, 0, err)
        self.assertIn("conflict", out)

    def test_retro_signals_blocks(self):
        epic, sid = self._make_epic_with_story()
        btid = self.store.create_task("build: s", step="build", role="coder", parent=sid)
        self.store.update_status(btid, "in_progress")
        self.store.update_status(btid, "open")
        rc, out, err = call(_cli_mod.cmd_retro, epic)
        self.assertEqual(rc, 0, err)
        self.assertIn("blocks=1", out)


class TestWorklog(unittest.TestCase):
    def setUp(self):
        _fake_setUp(self)

    def _close_story(self, title="feat: shipped-thing", reason="merged"):
        sid = self.store.create_story(title)
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
        self.assertIn("no stories", out)

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
        self.assertIn("no stories", out)

    def test_worklog_shows_pr_link_when_present(self):
        sid = self._close_story()
        self.store.update_metadata(sid, {"artifacts": [{"type": "pr", "value": "https://github.com/x/y/pull/9"}]})
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
        self.store.create_task("build: t", step="build", role="coder")
        rc, out, err = call(_cli_mod.cmd_worklog)
        self.assertEqual(rc, 0, err)
        self.assertIn("no stories", out)

    def test_worklog_shows_title_and_outcome(self):
        self._close_story(title="shipped-thing", reason="done")
        rc, out, err = call(_cli_mod.cmd_worklog)
        self.assertEqual(rc, 0, err)
        self.assertIn("shipped-thing", out)
        self.assertIn("done", out)

    def test_worklog_appears_in_help(self):
        r = run_tg("--help")
        self.assertIn("worklog", r.stdout)


if __name__ == "__main__":
    unittest.main()
