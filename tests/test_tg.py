import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TG = str(ROOT / "bin" / "tg")


def run_tg(*args, root=None):
    env = dict(os.environ)
    if root:
        env["GRID_ROOT_OVERRIDE"] = root
    return subprocess.run([sys.executable, TG, *args], capture_output=True, text=True, env=env)


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


def new_store_with_origin():
    """A grid store that is a git repo with an `origin` whose `main` branch exists,
    so `git worktree add ... origin/main` resolves."""
    remote = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", "--bare", remote], check=True)
    d = tempfile.mkdtemp()
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


def write_agents(root, roles=("coder", "reviewer", "pr-watcher", "driver")):
    """Write the standard pipeline agents (routing only, no artifact contracts)."""
    adir = Path(root) / "agents"
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


def write_contract_agents(root, specs=None):
    """Write agents that declare accepts/produces artifact contracts."""
    specs = specs or _CONTRACT_SPECS
    adir = Path(root) / "agents"
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
        write_agents(self.root)

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
        write_agents(self.root)

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
        for d in ("agents", "logs"):
            (Path(self.root) / d).mkdir(exist_ok=True)
        for r in ("coder", "reviewer", "pr-watcher"):
            (Path(self.root) / "agents" / ("%s.md" % r)).write_text(
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
        for d in ("agents", "logs", "flows"):
            (Path(self.root) / d).mkdir(exist_ok=True)
        for r in ("coder", "reviewer", "pr-watcher"):
            (Path(self.root) / "agents" / ("%s.md" % r)).write_text(
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
        # A coder is already booting (alive, has not claimed yet -> bead None).
        bd_in(self.root, "create", "build: t", "-t", "task", "-l", "for:coder,step:build", "--json")
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(
            [{"spawnid": "boot", "role": "coder", "pid": os.getpid(), "log": "x", "bead": None}]))
        r = self._run_once()
        self.assertEqual(r.returncode, 0, r.stderr)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertEqual(len(workers), 1)  # no second coder spawned

    def test_run_spawns_when_prior_worker_already_claimed(self):
        bd_in(self.root, "create", "build: t", "-t", "task", "-l", "for:coder,step:build", "--json")
        # prior coder already claimed something (bead set) -> not inflight
        (Path(self.root) / "logs" / "workers.json").write_text(json.dumps(
            [{"spawnid": "old", "role": "coder", "pid": os.getpid(), "log": "x", "bead": "other-1"}]))
        r = self._run_once()
        self.assertEqual(r.returncode, 0, r.stderr)
        workers = json.loads((Path(self.root) / "logs" / "workers.json").read_text())
        self.assertEqual(len(workers), 2)  # a fresh coder spawned for the ready task


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
        write_agents(self.root)

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


class TestClaimArtifacts(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_agents(self.root)

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
        write_agents(self.root)

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
        (Path(self.root) / "agents").mkdir(exist_ok=True)
        (Path(self.root) / "agents" / "coder.md").write_text(
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

    def test_parse_agent_extracts_model_and_strips_frontmatter(self):
        tg = self._tg()
        a = tg.parse_agent("coder")
        self.assertEqual(a["meta"]["model"], "sonnet")
        self.assertTrue(a["body"].startswith("# Coder"))
        self.assertNotIn("model:", a["body"])

    def test_parse_agent_reads_nested_routes(self):
        (Path(self.root) / "agents" / "reviewer.md").write_text(
            "---\nmodel: opus\nstep: review\nroutes:\n  done: open-pr\n"
            "  rejected: build\n---\n# Reviewer\n")
        tg = self._tg()
        a = tg.parse_agent("reviewer")
        self.assertEqual(a["meta"]["step"], "review")
        self.assertEqual(a["meta"]["routes"], {"done": "open-pr", "rejected": "build"})
        self.assertTrue(a["body"].startswith("# Reviewer"))


class TestFlowFromAgents(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_agents(self.root)

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
        write_agents(self.root)

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
        (Path(self.root) / "agents" / "reviewer.md").write_text("no frontmatter here")
        env = dict(os.environ, GRID_ROOT_OVERRIDE=self.root, GRID_SPAWN_CMD="echo x >> {log}")
        r = subprocess.run([sys.executable, TG, "spawn", "reviewer"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("model", r.stderr)


class TestArtifactContracts(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_contract_agents(self.root)

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
        write_contract_agents(self.root, specs)
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

    def test_init_creates_store(self):
        d = self._bare()
        r = run_tg("init", root=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(d, ".beads")))

    def test_init_idempotent(self):
        d = self._bare()
        run_tg("init", root=d)
        r = run_tg("init", root=d)
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
        write_agents(self.root)  # no requires/produces

    def test_done_without_contract_needs_no_artifacts(self):
        b = json.loads(bd_in(self.root, "create", "build: t", "-t", "task",
                             "-l", "for:coder,step:build", "--json"))["id"]
        r = run_tg("done", b, "done", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestWorktree(unittest.TestCase):
    def setUp(self):
        self.root = new_store_with_origin()
        write_agents(self.root)

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
        self.assertEqual(self._branch_of(ws), "grid/%s" % sid)

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
        self.assertEqual(branches[0]["value"], "grid/%s" % sid)

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
        self.assertEqual(self._branch_of(ws2), "grid/%s" % sid)
        self.assertTrue(os.path.isfile(os.path.join(ws2, "f.txt")))


class TestWorktreeNoOrigin(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        write_agents(self.root)

    def test_claim_omits_workspace_without_origin(self):
        bd_in(self.root, "create", "build: t", "-t", "task",
              "-l", "for:coder,step:build", "--json")
        t = json.loads(run_tg("claim", "coder", root=self.root).stdout)
        self.assertEqual(t["status"], "in-progress")
        self.assertNotIn("workspace", t)


if __name__ == "__main__":
    unittest.main()
