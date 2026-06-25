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


class TestSkeleton(unittest.TestCase):
    def test_help_lists_subcommands(self):
        r = run_tg("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for verb in ("status", "claim", "done", "block", "run", "sweep"):
            self.assertIn(verb, r.stdout)

    def test_unknown_subcommand_exits_2(self):
        r = run_tg("wibble")
        self.assertEqual(r.returncode, 2)


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


class TestFlow(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        flows = Path(self.root) / "flows"
        flows.mkdir()
        (flows / "feature.tsv").write_text(
            "build\tdone\treview\treviewer\n"
            "review\tdone\topen-pr\tpr-watcher\n"
            "review\trejected\tbuild\tcoder\n"
        )

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
        flows = Path(self.root) / "flows"
        flows.mkdir()
        (flows / "feature.tsv").write_text("build\tdone\treview\treviewer\n")

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
        flows = Path(self.root) / "flows"; flows.mkdir()
        (flows / "feature.tsv").write_text("build\tdone\treview\treviewer\n")

    def test_file_creates_story_with_spec_and_build_task(self):
        sid = run_tg("file", "specs/HSS-435.md", root=self.root).stdout.strip()
        self.assertTrue(sid)
        story = json.loads(bd_in(self.root, "show", sid, "--json"))[0]
        self.assertEqual(story["issue_type"], "story")
        self.assertEqual(story["metadata"]["artifacts"][0]["value"], "specs/HSS-435.md")
        kids = json.loads(bd_in(self.root, "children", sid, "--json"))
        self.assertEqual(len(kids), 1)
        kid_step = json.loads(run_tg("show", kids[0]["id"], root=self.root).stdout)["step"]
        self.assertEqual(kid_step, "build")

    def test_advance_parents_next_task_to_same_story(self):
        sid = run_tg("file", "specs/X.md", root=self.root).stdout.strip()
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
        flows = Path(self.root) / "flows"; flows.mkdir()
        (flows / "feature.tsv").write_text("build\tdone\treview\treviewer\n")

    def test_claim_surfaces_story_artifacts(self):
        run_tg("file", "specs/Y.md", root=self.root)
        r = run_tg("claim", "coder", root=self.root)
        t = json.loads(r.stdout)
        self.assertEqual(t["story_artifacts"][0]["value"], "specs/Y.md")

    def test_set_is_gone(self):
        r = run_tg("set", "x", "--pr", "y", root=self.root)
        self.assertEqual(r.returncode, 2)


class TestTrace(unittest.TestCase):
    def setUp(self):
        self.root = new_store()
        flows = Path(self.root) / "flows"; flows.mkdir()
        (flows / "feature.tsv").write_text("build\tdone\treview\treviewer\n")

    def test_trace_shows_story_artifacts_and_tasks(self):
        sid = run_tg("file", "specs/Z.md", root=self.root).stdout.strip()
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


if __name__ == "__main__":
    unittest.main()
