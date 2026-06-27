import json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TG = str(ROOT / "bin" / "tg")

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


def new_store():
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(
        ["bd", "init", "--skip-agents", "--skip-hooks", "--non-interactive", "--quiet"],
        cwd=d, check=True,
    )
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
    subprocess.run(
        ["bd", "init", "--skip-agents", "--skip-hooks", "--non-interactive", "--quiet"],
        cwd=d, check=True,
    )
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
        self.root = new_store()

    def test_task_mapping_and_status(self):
        bid = json.loads(bd_in(self.root, "create", "build: thing", "-t", "task",
                               "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("show", bid, root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        t = json.loads(r.stdout)
        self.assertEqual(t["role"], "coder")
        self.assertEqual(t["step"], "build")
        self.assertEqual(t["type"], "task")
        self.assertEqual(t["status"], "ready")

    def test_status_buckets_json(self):
        h = json.loads(bd_in(self.root, "create", "spec: x", "-t", "task",
                             "-l", "for:human,step:spec", "--json"))["id"]
        c = json.loads(bd_in(self.root, "create", "build: y", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("status", "--json", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads(r.stdout)
        self.assertIn(h, [t["id"] for t in s["mine"]])
        self.assertIn(c, [t["id"] for t in s["queue"]])


class TestClaim(unittest.TestCase):
    def setUp(self):
        self.root = new_store()

    def test_claim_returns_and_marks_in_progress(self):
        c = json.loads(bd_in(self.root, "create", "build: y", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("claim", "coder", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        t = json.loads(r.stdout)
        self.assertEqual(t["id"], c)
        self.assertEqual(t["status"], "in-progress")
        r2 = run_tg("claim", "coder", root=self.root)
        self.assertEqual(r2.stdout.strip(), "")

    def test_claim_ignores_human(self):
        bd_in(self.root, "create", "spec: x", "-t", "task", "-l", "for:human,step:spec", "--json")
        r = run_tg("claim", "coder", root=self.root)
        self.assertEqual(r.stdout.strip(), "")

    def test_claim_assigns_worker_spawnid(self):
        b = json.loads(bd_in(self.root, "create", "build: y", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        env = dict(os.environ, GRID_ROOT_OVERRIDE=self.root, GRID_SPAWNID="spawn-xyz")
        r = subprocess.run([sys.executable, TG, "claim", "coder"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        bead = json.loads(bd_in(self.root, "show", b, "--json"))[0]
        self.assertEqual(bead.get("assignee"), "spawn-xyz")


class TestFlow(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_steps(self.root)

    def test_advance_creates_next_step(self):
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        bd_in(self.root, "close", b, "--reason", "done")
        r = run_tg("advance", b, "done", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        new = r.stdout.strip()
        self.assertTrue(new)
        nt = json.loads(run_tg("show", new, root=self.root).stdout)
        self.assertEqual(nt["role"], "reviewer")
        self.assertEqual(nt["step"], "review")

    def test_ready_roles(self):
        bd_in(self.root, "create", "build: t", "-t", "task", "-l", "for:coder,step:build", "--json")
        r = run_tg("ready-roles", root=self.root)
        self.assertIn("coder", r.stdout.split())


class TestDoneBlock(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_steps(self.root)

    def test_done_closes_and_advances(self):
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        bd_in(self.root, "note", b, "spec: specs/T.md")
        r = run_tg("done", b, "done", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip())
        st = json.loads(bd_in(self.root, "show", b, "--json"))[0]["status"]
        self.assertEqual(st, "closed")

    def test_done_unknown_outcome_errors_without_closing(self):
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("done", b, "banana", root=self.root)
        self.assertEqual(r.returncode, 1)
        st = json.loads(bd_in(self.root, "show", b, "--json"))[0]["status"]
        self.assertEqual(st, "open")

    def test_block_writes_metadata_and_routes_human(self):
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("block", b, "--branch", "grid/x", "--needs", "confirm aud", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        bead = json.loads(bd_in(self.root, "show", b, "--json"))[0]
        self.assertEqual(bead["metadata"]["branch"], "grid/x")
        self.assertEqual(bead["metadata"]["needs"], "confirm aud")
        self.assertIn("for:human", bead["labels"])
        self.assertNotIn("for:coder", bead["labels"])

    def test_block_clears_assignee_and_surfaces_in_mine(self):
        # A claimed task (assignee set) that gets blocked must clear the assignee,
        # else it stays "in-progress" and hides in `tg active` instead of `tg mine`.
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        bd_in(self.root, "ready", "--label", "for:coder", "--claim", "--json")
        r = run_tg("block", b, "--needs", "rebase first", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        bead = json.loads(bd_in(self.root, "show", b, "--json"))[0]
        self.assertIn(bead.get("assignee"), (None, ""))
        self.assertIn(b, run_tg("mine", root=self.root).stdout)

    def test_done_note_forwards_to_next_task(self):
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("done", b, "done", "--note", "fix the coverage", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        new = r.stdout.strip()
        self.assertTrue(new)
        bead = json.loads(bd_in(self.root, "show", new, "--json"))[0]
        notes = bead.get("notes", "")
        self.assertIn("from build (done):", notes)
        self.assertIn("fix the coverage", notes)

    def test_done_without_note_unchanged(self):
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("done", b, "done", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        new = r.stdout.strip()
        self.assertTrue(new)
        bead = json.loads(bd_in(self.root, "show", new, "--json"))[0]
        self.assertNotIn("from build", bead.get("notes", ""))


class TestSweep(unittest.TestCase):
    def setUp(self):
        self.root = new_store()

    def test_sweep_releases_orphaned_claim(self):
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        bd_in(self.root, "ready", "--label", "for:coder", "--claim", "--json")
        r = run_tg("sweep", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        bead = json.loads(bd_in(self.root, "show", b, "--json"))[0]
        self.assertEqual(bead["status"], "open")
        self.assertIn(bead.get("assignee"), (None, ""))

    def test_sweep_keeps_task_of_live_worker_before_stamp(self):
        # Reproduces the double-claim TOCTOU: a worker has claimed the task
        # (assignee = its spawnid) but has not yet stamped its registry bead.
        # Sweep must NOT reclaim it - the owning worker is alive.
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        (Path(self.root) / "logs").mkdir(exist_ok=True)
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(
            [{"spawnid": "S", "role": "coder", "pid": os.getpid(), "log": "x", "bead": None}]))
        bd_in(self.root, "assign", b, "S")
        bd_in(self.root, "update", b, "--status", "in_progress")
        r = run_tg("sweep", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        bead = json.loads(bd_in(self.root, "show", b, "--json"))[0]
        self.assertEqual(bead["status"], "in_progress")
        self.assertEqual(bead.get("assignee"), "S")

    def test_sweep_reclaims_dead_worker_claim(self):
        dead = subprocess.Popen(["true"]); dead.wait()
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        (Path(self.root) / "logs").mkdir(exist_ok=True)
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(
            [{"spawnid": "D", "role": "coder", "pid": dead.pid, "log": "x", "bead": b}]))
        bd_in(self.root, "assign", b, "D")
        bd_in(self.root, "update", b, "--status", "in_progress")
        r = run_tg("sweep", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        bead = json.loads(bd_in(self.root, "show", b, "--json"))[0]
        self.assertEqual(bead["status"], "open")


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
        self.root = new_store()

    def test_add_creates_standalone_human_task(self):
        r = run_tg("add", "look at X later", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        new = r.stdout.strip()
        self.assertTrue(new)
        t = json.loads(run_tg("show", new, root=self.root).stdout)
        self.assertEqual(t["role"], "human")
        self.assertEqual(t["status"], "needs-human")
        self.assertIsNone(t["step"])
        self.assertEqual(t["title"], "look at X later")

    def test_add_shows_in_mine_not_queue(self):
        run_tg("add", "remind me", root=self.root)
        mine = run_tg("mine", root=self.root).stdout
        self.assertIn("remind me", mine)
        # standalone human task must NOT be claimable by an agent
        r = run_tg("claim", "coder", root=self.root)
        self.assertEqual(r.stdout.strip(), "")


class TestArtifacts(unittest.TestCase):
    def setUp(self):
        self.root = new_store()

    def _tg_module(self):
        import importlib.util
        from importlib.machinery import SourceFileLoader
        os.environ["GRID_ROOT_OVERRIDE"] = self.root
        loader = SourceFileLoader("tgmod", TG)
        spec = importlib.util.spec_from_loader("tgmod", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def test_add_and_read_artifacts_append(self):
        sid = json.loads(bd_in(self.root, "create", "story s", "-t", "story", "--json"))["id"]
        tg = self._tg_module()
        tg.add_artifact(sid, "spec", "specs/X.md")
        tg.add_artifact(sid, "pr", "https://gh/9", "PR 9")
        arts = tg.story_artifacts(sid)
        self.assertEqual(len(arts), 2)
        self.assertEqual(arts[0]["type"], "spec")
        self.assertEqual(arts[1]["type"], "pr")
        self.assertEqual(arts[1]["label"], "PR 9")


class TestLink(unittest.TestCase):
    def setUp(self):
        self.root = new_store()

    def test_link_appends_artifact(self):
        sid = json.loads(bd_in(self.root, "create", "story s", "-t", "story", "--json"))["id"]
        r = run_tg("link", sid, "pr", "https://gh/9", "--label", "PR 9", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        meta = json.loads(bd_in(self.root, "show", sid, "--json"))[0]["metadata"]
        arts = meta["artifacts"]
        self.assertEqual(arts[0]["type"], "pr")
        self.assertEqual(arts[0]["value"], "https://gh/9")
        self.assertEqual(arts[0]["label"], "PR 9")


class TestModelV2(unittest.TestCase):
    def setUp(self):
        self.root = new_store()

    def test_task_exposes_type_parent_and_parent_artifacts(self):
        epic = json.loads(bd_in(self.root, "create", "epic e", "-t", "epic", "--json"))["id"]
        story = json.loads(bd_in(self.root, "create", "story s", "-t", "story",
                                 "--parent", epic, "--json"))["id"]
        bd_in(self.root, "update", story, "--metadata",
              json.dumps({"artifacts": [{"type": "spec", "value": "specs/X.md"}]}))
        task = json.loads(bd_in(self.root, "create", "build: b", "-t", "task",
                                "-l", "for:coder,step:build", "--parent", story, "--json"))["id"]
        v = json.loads(run_tg("show", task, root=self.root).stdout)
        self.assertEqual(v["type"], "task")
        self.assertEqual(v["parent"], story)
        self.assertEqual(v["story_artifacts"][0]["value"], "specs/X.md")


class TestFileStory(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_steps(self.root)

    def test_file_creates_story_with_spec_and_build_task(self):
        sid = run_tg("file", "specs/HSS-435.md", "--step", "build", root=self.root).stdout.strip()
        self.assertTrue(sid)
        story = json.loads(bd_in(self.root, "show", sid, "--json"))[0]
        self.assertEqual(story["issue_type"], "story")
        self.assertEqual(story["metadata"]["artifacts"][0]["value"], "specs/HSS-435.md")
        kids = json.loads(bd_in(self.root, "children", sid, "--json"))
        self.assertEqual(len(kids), 1)
        kid_step = json.loads(run_tg("show", kids[0]["id"], root=self.root).stdout)["step"]
        self.assertEqual(kid_step, "build")

    def test_advance_parents_next_task_to_same_story(self):
        sid = run_tg("file", "specs/X.md", "--step", "build", root=self.root).stdout.strip()
        build = json.loads(bd_in(self.root, "children", sid, "--json"))[0]["id"]
        bd_in(self.root, "close", build, "--reason", "done")
        new = run_tg("advance", build, "done", root=self.root).stdout.strip()
        nt = json.loads(run_tg("show", new, root=self.root).stdout)
        self.assertEqual(nt["parent"], sid)
        self.assertEqual(nt["step"], "review")
        self.assertEqual(nt["story_artifacts"][0]["value"], "specs/X.md")


class TestFileBlockedBy(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_steps(self.root)

    def test_blocked_by_creates_dependency_on_first_task(self):
        gate = json.loads(bd_in(self.root, "create", "review-plan: foo", "-t", "task",
                                "-l", "for:human,step:review-plan", "--json"))["id"]
        sid = run_tg("file", "specs/X.md", "--step", "build",
                     "--blocked-by", gate, root=self.root).stdout.strip()
        self.assertTrue(sid)
        task_id = json.loads(bd_in(self.root, "children", sid, "--json"))[0]["id"]
        deps = json.loads(bd_in(self.root, "dep", "list", task_id, "--json"))
        blocker_ids = [d["id"] for d in deps]
        self.assertIn(gate, blocker_ids)

    def test_blocked_task_not_claimable_until_gate_closes(self):
        gate = json.loads(bd_in(self.root, "create", "review-plan: foo", "-t", "task",
                                "-l", "for:human,step:review-plan", "--json"))["id"]
        run_tg("file", "specs/X.md", "--step", "build",
               "--blocked-by", gate, root=self.root)
        r = run_tg("claim", "coder", root=self.root)
        self.assertEqual(r.stdout.strip(), "")  # not claimable while gate is open
        bd_in(self.root, "close", gate, "--reason", "approved")
        r2 = run_tg("claim", "coder", root=self.root)
        self.assertTrue(r2.stdout.strip())  # now claimable

    def test_multiple_blocked_by_ids(self):
        gate1 = json.loads(bd_in(self.root, "create", "gate1", "-t", "task",
                                 "-l", "for:human", "--json"))["id"]
        gate2 = json.loads(bd_in(self.root, "create", "gate2", "-t", "task",
                                 "-l", "for:human", "--json"))["id"]
        sid = run_tg("file", "specs/X.md", "--step", "build",
                     "--blocked-by", gate1, "--blocked-by", gate2,
                     root=self.root).stdout.strip()
        task_id = json.loads(bd_in(self.root, "children", sid, "--json"))[0]["id"]
        deps = json.loads(bd_in(self.root, "dep", "list", task_id, "--json"))
        blocker_ids = {d["id"] for d in deps}
        self.assertIn(gate1, blocker_ids)
        self.assertIn(gate2, blocker_ids)


class TestClaimArtifacts(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_steps(self.root)

    def test_claim_surfaces_story_artifacts(self):
        run_tg("file", "specs/Y.md", "--step", "build", root=self.root)
        r = run_tg("claim", "coder", root=self.root)
        t = json.loads(r.stdout)
        self.assertEqual(t["story_artifacts"][0]["value"], "specs/Y.md")

    def test_set_is_gone(self):
        r = run_tg("set", "x", "--pr", "y", root=self.root)
        self.assertEqual(r.returncode, 2)


class TestTrace(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_steps(self.root)

    def test_trace_shows_story_artifacts_and_tasks(self):
        sid = run_tg("file", "specs/Z.md", "--step", "build", root=self.root).stdout.strip()
        r = run_tg("trace", sid, "--json", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        tr = json.loads(r.stdout)
        self.assertEqual(tr["story"]["id"], sid)
        self.assertEqual(tr["artifacts"][0]["value"], "specs/Z.md")
        self.assertEqual(len(tr["tasks"]), 1)
        self.assertEqual(tr["tasks"][0]["step"], "build")


class TestAgentFrontmatter(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
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
        self.root = new_store()
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
        self.root = new_store()
        write_contract_steps(self.root)

    def _bead(self, bid):
        return json.loads(bd_in(self.root, "show", bid, "--json"))[0]

    def test_claim_escalates_when_required_input_missing(self):
        b = json.loads(bd_in(self.root, "create", "build: x", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("claim", "coder", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "")  # not claimed
        bead = self._bead(b)
        self.assertIn("for:human", bead["labels"])
        self.assertNotIn("for:coder", bead["labels"])
        self.assertEqual(bead["status"], "open")

    def test_claim_proceeds_when_inputs_present(self):
        sid = run_tg("file", "specs/X.md", "--step", "build", root=self.root).stdout.strip()
        r = run_tg("claim", "coder", root=self.root)
        t = json.loads(r.stdout)
        self.assertEqual(t["status"], "in-progress")
        self.assertEqual(t["parent"], sid)

    def test_done_refused_when_required_output_missing(self):
        sid = run_tg("file", "specs/X.md", "--step", "build", root=self.root).stdout.strip()
        task = json.loads(bd_in(self.root, "children", sid, "--json"))[0]["id"]
        r = run_tg("done", task, "done", root=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("branch", r.stderr)
        self.assertEqual(self._bead(task)["status"], "open")

    def test_done_succeeds_when_output_present(self):
        sid = run_tg("file", "specs/X.md", "--step", "build", root=self.root).stdout.strip()
        task = json.loads(bd_in(self.root, "children", sid, "--json"))[0]["id"]
        run_tg("link", sid, "branch", "grid/x", root=self.root)
        r = run_tg("done", task, "done", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._bead(task)["status"], "closed")

    def test_file_rejects_non_entry_step(self):
        r = run_tg("file", "specs/X.md", "--step", "review", root=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("branch", r.stderr)

    def test_flow_reports_composition_ok(self):
        r = run_tg("flow", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("branch", r.stdout)  # produces shown

    def test_flow_flags_broken_composition(self):
        specs = {k: dict(v) for k, v in _CONTRACT_SPECS.items()}
        specs["reviewer"] = dict(specs["reviewer"],
                                 accepts={"spec": "required", "design": "required"})
        write_contract_steps(self.root, specs)
        r = run_tg("flow", root=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("design", r.stderr)


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
        self.root = new_store()
        write_steps(self.root)  # no requires/produces

    def test_done_without_contract_needs_no_artifacts(self):
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("done", b, "done", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)


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
        self.root = new_store()
        write_steps(self.root)

    def test_unblock_returns_blocked_task_to_agent_role(self):
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        bd_in(self.root, "ready", "--label", "for:coder", "--claim", "--json")  # claim it
        run_tg("block", b, "--needs", "rebase first", root=self.root)
        r = run_tg("unblock", b, root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        bead = json.loads(bd_in(self.root, "show", b, "--json"))[0]
        self.assertIn("for:coder", bead["labels"])
        self.assertNotIn("for:human", bead["labels"])
        self.assertEqual(bead["status"], "open")
        self.assertIn(bead.get("assignee"), (None, ""))
        t = json.loads(run_tg("show", b, root=self.root).stdout)
        self.assertEqual(t["status"], "ready")
        self.assertEqual(t["role"], "coder")

    def test_unblock_refuses_human_step(self):
        (Path(self.root) / "steps" / "ready-merge.md").write_text(
            "---\nstep: ready-merge\nroutes:\n  merged: cleanup\n---\n# ready-merge\n")
        b = json.loads(bd_in(self.root, "create", "ready-merge: t", "-t", "task",
                             "-l", "for:human,step:ready-merge", "--json"))["id"]
        r = run_tg("unblock", b, root=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("ready-merge", r.stderr)


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
        self.root = new_store()
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
        self.root = new_store()
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
        self.root = new_store()
        adir = Path(self.root) / "steps"
        adir.mkdir(exist_ok=True)
        (adir / "coder.md").write_text(
            "---\nmodel: sonnet\nstep: build\nroutes:\n  done: review\n---\nstub")
        (adir / "ready-merge.md").write_text(
            "---\nstep: ready-merge\nroutes:\n  merged: cleanup\n  changes: build\n---\nstub")

    def test_mine_tags_orders_and_shows_context(self):
        run_tg("add", "look at X", root=self.root)                                  # todo
        sid = json.loads(bd_in(self.root, "create", "feat", "-t", "story", "--json"))["id"]
        bd_in(self.root, "update", sid, "--metadata",
              json.dumps({"artifacts": [{"type": "pr", "value": "http://pr/1"}]}))
        bd_in(self.root, "create", "merge: y", "-t", "task", "-l",
              "for:human,step:ready-merge", "--parent", sid, "--json")             # action
        b = json.loads(bd_in(self.root, "create", "build: z", "-t", "task",
                             "-l", "for:human,step:build", "--json"))["id"]
        bd_in(self.root, "update", b, "--metadata", json.dumps({"needs": "rebase first"}))  # blocked
        out = run_tg("mine", root=self.root).stdout
        for tag in ("[blocked]", "[action]", "[todo]"):
            self.assertIn(tag, out)
        self.assertIn("merge: y", out)           # leads with the title
        self.assertIn("look at X", out)
        self.assertLess(out.index("[blocked]"), out.index("[action]"))
        self.assertLess(out.index("[action]"), out.index("[todo]"))

    def test_mine_shows_plan_doc_for_gate_task(self):
        gate = json.loads(bd_in(self.root, "create", "review-plan: foo", "-t", "task",
                                "-l", "for:human,step:ready-merge", "--json"))["id"]
        bd_in(self.root, "update", gate, "--metadata",
              json.dumps({"artifacts": [{"type": "plan-doc", "value": "/tmp/plan.md"}]}))
        out = run_tg("mine", root=self.root).stdout
        self.assertIn("plan:/tmp/plan.md", out)


class TestReflect(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_steps(self.root)
        self.cfg = write_config()

    def _file_story(self, spec_path=None):
        sid = json.loads(bd_in(self.root, "create", "feat", "-t", "story", "--json"))["id"]
        arts = [{"type": "spec", "value": spec_path or "/tmp/no-spec.md"}]
        bd_in(self.root, "update", sid, "--metadata", json.dumps({"artifacts": arts}))
        tid = json.loads(bd_in(self.root, "create", "build: feat", "-t", "task",
                               "-l", "for:coder,step:build", "--parent", sid, "--json"))["id"]
        return sid, tid

    def test_reflect_stores_artifact_on_story(self):
        sid, tid = self._file_story()
        r = run_tg("reflect", tid, "--used", "Summary,Scope", "--skipped", "Risks",
                   root=self.root, config=self.cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("reflected", r.stdout)
        arts = json.loads(bd_in(self.root, "show", sid, "--json"))[0].get("metadata", {}).get("artifacts", [])
        refs = [a for a in arts if a["type"] == "reflection"]
        self.assertEqual(len(refs), 1)
        data = json.loads(refs[0]["value"])
        self.assertEqual(data["sections"]["Summary"], "used")
        self.assertEqual(data["sections"]["Scope"], "used")
        self.assertEqual(data["sections"]["Risks"], "skipped")
        self.assertEqual(data["task"], tid)

    def test_reflect_records_guess_missing_noise(self):
        sid, tid = self._file_story()
        r = run_tg("reflect", tid,
                   "--guess", "Decisions",
                   "--missing", "acceptance criteria",
                   "--missing", "error cases",
                   "--noise", "Out of scope",
                   root=self.root, config=self.cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        arts = json.loads(bd_in(self.root, "show", sid, "--json"))[0].get("metadata", {}).get("artifacts", [])
        data = json.loads(next(a for a in arts if a["type"] == "reflection")["value"])
        self.assertEqual(data["sections"]["Decisions"], "guess")
        self.assertIn("acceptance criteria", data["missing"])
        self.assertIn("error cases", data["missing"])
        self.assertIn("Out of scope", data["noise"])

    def test_reflect_multiple_calls_append(self):
        sid, tid = self._file_story()
        run_tg("reflect", tid, "--used", "Summary", root=self.root, config=self.cfg)
        run_tg("reflect", tid, "--used", "Scope", root=self.root, config=self.cfg)
        arts = json.loads(bd_in(self.root, "show", sid, "--json"))[0].get("metadata", {}).get("artifacts", [])
        refs = [a for a in arts if a["type"] == "reflection"]
        self.assertEqual(len(refs), 2)

    def test_reflect_stamps_spec_hash(self):
        import tempfile
        spec = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
        spec.write("# spec\ncontent")
        spec.close()
        sid, tid = self._file_story(spec_path=spec.name)
        bd_in(self.root, "update", sid, "--metadata",
              json.dumps({"artifacts": [{"type": "spec", "value": spec.name}]}))
        run_tg("reflect", tid, "--used", "spec", root=self.root, config=self.cfg)
        arts = json.loads(bd_in(self.root, "show", sid, "--json"))[0].get("metadata", {}).get("artifacts", [])
        data = json.loads(next(a for a in arts if a["type"] == "reflection")["value"])
        self.assertNotEqual(data["spec_hash"], "unknown")
        self.assertEqual(len(data["spec_hash"]), 8)

    def test_reflect_no_sections_still_valid(self):
        sid, tid = self._file_story()
        r = run_tg("reflect", tid, root=self.root, config=self.cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        arts = json.loads(bd_in(self.root, "show", sid, "--json"))[0].get("metadata", {}).get("artifacts", [])
        data = json.loads(next(a for a in arts if a["type"] == "reflection")["value"])
        self.assertEqual(data["sections"], {})
        self.assertEqual(data["missing"], [])
        self.assertEqual(data["noise"], [])


class TestRetro(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_steps(self.root)
        self.cfg = write_config()

    def _make_epic_with_story(self, sid=None):
        epic = json.loads(bd_in(self.root, "create", "epic-1", "-t", "story", "--json"))["id"]
        if sid is None:
            sid = json.loads(bd_in(
                self.root, "create", "story-1", "-t", "story",
                "--parent", epic, "--json"))["id"]
        return epic, sid

    def test_retro_no_reflections(self):
        epic, _ = self._make_epic_with_story()
        r = run_tg("retro", epic, root=self.root, config=self.cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("N=0", r.stdout)
        self.assertIn("no reflections yet", r.stdout)
        self.assertIn("Per-story signals", r.stdout)

    def test_retro_aggregates_section_counts(self):
        epic, sid = self._make_epic_with_story()
        tid = json.loads(bd_in(self.root, "create", "build: s", "-t", "task",
                               "-l", "for:coder,step:build", "--parent", sid, "--json"))["id"]
        run_tg("reflect", tid, "--used", "Summary,Scope", "--skipped", "Risks",
               root=self.root, config=self.cfg)
        r = run_tg("retro", epic, root=self.root, config=self.cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("N=1", r.stdout)
        self.assertIn("Summary", r.stdout)
        self.assertIn("used=1", r.stdout)
        self.assertIn("Risks", r.stdout)
        self.assertIn("skipped=1", r.stdout)

    def test_retro_aggregates_missing_and_noise(self):
        epic, sid = self._make_epic_with_story()
        tid = json.loads(bd_in(self.root, "create", "build: s", "-t", "task",
                               "-l", "for:coder,step:build", "--parent", sid, "--json"))["id"]
        run_tg("reflect", tid, "--missing", "edge case coverage",
               "--noise", "Out of scope", root=self.root, config=self.cfg)
        r = run_tg("retro", epic, root=self.root, config=self.cfg)
        self.assertIn("edge case coverage", r.stdout)
        self.assertIn("Out of scope", r.stdout)

    def test_retro_signals_review_rounds(self):
        epic, sid = self._make_epic_with_story()
        bd_in(self.root, "create", "review: s", "-t", "task",
              "-l", "for:reviewer,step:review", "--parent", sid, "--json")
        rtid = json.loads(bd_in(self.root, "create", "review: s2", "-t", "task",
                                "-l", "for:reviewer,step:review", "--parent", sid, "--json"))["id"]
        bd_in(self.root, "close", rtid, "--reason", "rejected")
        r = run_tg("retro", epic, root=self.root, config=self.cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("rounds=1", r.stdout)

    def test_retro_signals_conflict(self):
        epic, sid = self._make_epic_with_story()
        pr_tid = json.loads(bd_in(self.root, "create", "open-pr: s", "-t", "task",
                                  "-l", "for:pr-watcher,step:open-pr",
                                  "--parent", sid, "--json"))["id"]
        bd_in(self.root, "close", pr_tid, "--reason", "conflict-rebase")
        r = run_tg("retro", epic, root=self.root, config=self.cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("conflict", r.stdout)

    def test_retro_signals_blocks(self):
        epic, sid = self._make_epic_with_story()
        btid = json.loads(bd_in(self.root, "create", "build: s", "-t", "task",
                                "-l", "for:coder,step:build", "--parent", sid, "--json"))["id"]
        bd_in(self.root, "update", btid, "--status", "in_progress")
        bd_in(self.root, "update", btid, "--status", "open")
        r = run_tg("retro", epic, root=self.root, config=self.cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("blocks=1", r.stdout)


if __name__ == "__main__":
    unittest.main()
