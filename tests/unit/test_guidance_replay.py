import json
import tempfile
import unittest
from pathlib import Path

from scripts import guidance_replay as gr


def pair(entry, prob, cited, size, step="s"):
    return {
        "step": step, "stage": "write-code", "entry": entry, "prob": prob,
        "cited": cited, "size": size, "brief": "brief",
    }


WORKED = [
    pair("A", 0.9, True, 100),
    pair("B", 0.5, True, 50),
    pair("C", 0.5, False, 200),
    pair("D", 0.2, False, 150),
]


def many(entry, n, cited, prob, size=10):
    return [pair(entry, prob, i < cited, size, step="s%d" % i) for i in range(n)]


class MetricsTest(unittest.TestCase):
    def test_exact_hit_threshold_keeps_equal_probability(self):
        m = gr.metrics_at(WORKED, 0.5)
        self.assertAlmostEqual(m["saved"], 0.30)
        self.assertEqual(m["cited_dropped"], 0)
        self.assertAlmostEqual(m["precision"], 2 / 3)
        self.assertEqual(m["recall"], 1.0)

    def test_threshold_that_drops_a_cited_pair(self):
        m = gr.metrics_at(WORKED, 0.6)
        self.assertAlmostEqual(m["saved"], 0.80)
        self.assertEqual(m["cited_dropped"], 1)
        self.assertEqual(m["precision"], 1.0)
        self.assertEqual(m["recall"], 0.5)

    def test_tags_alone_precision_is_cited_over_delivered(self):
        base = gr.tags_alone(WORKED)
        self.assertEqual(base["precision"], 0.5)
        self.assertEqual(base["recall"], 1.0)


class HighCitationTest(unittest.TestCase):
    def test_nine_deliveries_fully_cited_is_not_high(self):
        self.assertEqual(gr.high_citation(many("E", 9, 9, 0.9)), [])

    def test_ten_deliveries_half_cited_is_high(self):
        self.assertEqual(gr.high_citation(many("E", 10, 5, 0.9)), ["E"])

    def test_ten_deliveries_just_under_half_is_not_high(self):
        self.assertEqual(gr.high_citation(many("E", 10, 4, 0.9)), [])


class VerdictTest(unittest.TestCase):
    def fixture(self, junk_bytes):
        keep = many("K", 10, 10, 0.9, size=100)
        junk = many("J", 10, 0, 0.1, size=junk_bytes)
        return keep + junk

    def test_exactly_the_bar_beats(self):
        ev = gr.evaluate(self.fixture(25))
        self.assertTrue(ev["beats"])
        self.assertAlmostEqual(ev["best"]["saved"], 0.20)

    def test_just_under_the_bar_does_not_beat(self):
        ev = gr.evaluate(self.fixture(24))
        self.assertFalse(ev["beats"])

    def test_no_qualifying_threshold_names_blocker(self):
        pairs = many("K", 10, 10, 0.05, size=100) + many("J", 10, 0, 0.9, size=100)
        ev = gr.evaluate(pairs)
        self.assertIsNone(ev["best"])
        self.assertFalse(ev["beats"])
        self.assertTrue(all(r["blockers"] == ["K"] for r in ev["rows"][1:]))


def spawn(step, project, stage="write-code", delivered=("A",), skipped=(), cited=()):
    return {
        "step": step, "item": "LC-" + step, "project": project, "stage": stage,
        "delivered": list(delivered), "skipped": list(skipped), "cited": list(cited),
        "brief": "brief for " + step, "step_text": "text",
    }


def envelope(reply, model="claude-haiku-5-5"):
    return json.dumps({
        "result": json.dumps(reply), "duration_ms": 100, "total_cost_usd": 0.1,
        "modelUsage": {model: {}},
    })


class ReplyValidationTest(unittest.TestCase):
    def run_with(self, replies):
        calls = []

        def run_claude(argv, prompt, cwd):
            calls.append(argv)
            return 0, replies[min(len(calls) - 1, len(replies) - 1)], ""

        with tempfile.TemporaryDirectory() as out:
            result = gr.score_spawns(
                [spawn("s1", "p", delivered=("A", "B"))], {}, out, run_claude, 0
            )
            kept = gr.read_jsonl(Path(out) / "scores.jsonl")
        return result, calls, kept

    def test_each_invalid_reply_retries_once_then_fails(self):
        for bad in (
            envelope({"A": 0.5}),
            envelope({"A": 0.5, "B": 0.5, "C": 0.5}),
            envelope({"A": 0.5, "B": 1.5}),
            "not json",
        ):
            result, calls, kept = self.run_with([bad])
            self.assertEqual(len(calls), 2)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(kept, [])

    def test_retry_that_succeeds_is_recorded(self):
        result, calls, kept = self.run_with([envelope({"A": 1}), envelope({"A": 0.2, "B": 0.4})])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["scored"], 1)
        self.assertEqual(kept[0]["probs"], {"A": 0.2, "B": 0.4})
        self.assertEqual(kept[0]["model_id"], "claude-haiku-5-5")
        self.assertEqual(kept[0]["prompt_version"], gr.PROMPT_VERSION)

    def test_call_uses_haiku_without_tools(self):
        _result, calls, _kept = self.run_with([envelope({"A": 0.2, "B": 0.4})])
        argv = calls[0]
        self.assertIn("haiku", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")


class ResumeTest(unittest.TestCase):
    def test_present_record_is_not_rescored_but_new_prompt_version_is(self):
        calls = []

        def run_claude(argv, prompt, cwd):
            calls.append(1)
            return 0, envelope({"A": 0.5}), ""

        spawns = [spawn("s1", "p")]
        with tempfile.TemporaryDirectory() as out:
            gr.score_spawns(spawns, {}, out, run_claude, 0)
            self.assertEqual(len(calls), 1)
            gr.score_spawns(spawns, {}, out, run_claude, 0)
            self.assertEqual(len(calls), 1)
            original = gr.PROMPT_VERSION
            gr.PROMPT_VERSION = "v2"
            try:
                gr.score_spawns(spawns, {}, out, run_claude, 0)
            finally:
                gr.PROMPT_VERSION = original
            self.assertEqual(len(calls), 2)


class SamplingTest(unittest.TestCase):
    def frame(self, sizes):
        out = []
        for project, n in sizes.items():
            out += [spawn("%s-%d" % (project, i), project) for i in range(n)]
        return out

    def test_fixed_seed_gives_fixed_sample(self):
        frame = self.frame({"a": 20, "b": 20, "c": 20})
        one = [s["step"] for s in gr.draw(frame, 15, 7)]
        two = [s["step"] for s in gr.draw(frame, 15, 7)]
        self.assertEqual(one, two)

    def test_fewer_than_three_projects_raises(self):
        with self.assertRaises(gr.ReplayError):
            gr.draw(self.frame({"a": 5, "b": 5}), 4, 0)

    def test_round_robin_caps_lopsided_project(self):
        drawn = gr.draw(self.frame({"a": 100, "b": 10, "c": 10}), 30, 0)
        counts = {}
        for s in drawn:
            counts[s["project"]] = counts.get(s["project"], 0) + 1
        self.assertEqual(counts, {"a": 10, "b": 10, "c": 10})


class ReadOnlyTest(unittest.TestCase):
    def test_every_argv_is_lc_with_a_read_verb(self):
        seen = []

        def run_lc(argv):
            seen.append(argv)
            verb = argv[1]
            if verb == "worklog":
                return "LC-1  title  [done]\n"
            if verb == "trace":
                return json.dumps({"steps": [{"id": "LC-1.1", "step": "write-code", "artifacts": [
                    {"type": "guidance-delivered", "value": "A\nB"}]}]})
            if verb == "show":
                return json.dumps({"repo": "r", "description": "d"})
            return "text"

        spawns = gr.collect_spawns("2026-01-01", "2026-01-14", run_lc)
        self.assertEqual(len(spawns), 1)
        self.assertEqual(spawns[0]["delivered"], ["A", "B"])
        self.assertEqual({a[1] for a in seen}, {"worklog", "trace", "show", "peek"})
        for argv in seen:
            self.assertEqual(argv[0], "lc")
            self.assertIn(argv[1], gr.LC_VERBS)

    def test_worklog_traces_items_of_every_shortcode(self):
        text = "LC-1  title  [done]\nRC-22  other  [done]\nLC-1  again  [done]\nnote line\n"
        self.assertEqual(gr.worklog_items(text), ["LC-1", "RC-22"])

    def test_write_verbs_are_refused(self):
        for verb in ("attach", "set", "done", "claim"):
            with self.assertRaises(gr.ReplayError):
                gr.lc_argv(verb)


class DirGit:
    def default_ref(self, root):
        return "main"

    def list_files_at(self, root, ref):
        return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*.md"))

    def read_file_at(self, root, ref, path):
        return (Path(root) / path).read_bytes()


def entry_file(status="stable"):
    return (
        "---\ntype: Guidance\nstatus: %s\nverified: 2026-01-01\napplies-to:\n"
        "  facets: [python]\n  steps: [write-code]\n---\nbody text here\n" % status
    )


class ReportTest(unittest.TestCase):
    def run_report(self, resolved, spawns):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "guidance"
            repo.mkdir()
            for e in resolved:
                (repo / ("%s.md" % e)).write_text(entry_file())
            (repo / "readme.md").write_text("no entry")
            out = Path(tmp) / "out"
            out.mkdir()
            (out / "sample.json").write_text(json.dumps(
                {"since": "a", "until": "b", "seed": 1, "spawns": spawns}))
            for s in spawns:
                gr.append_jsonl(out / "scores.jsonl", {
                    "step": s["step"], "prompt_version": gr.PROMPT_VERSION,
                    "model_id": "claude-haiku-5-5",
                    "probs": {e: 0.8 for e in s["delivered"] + s["skipped"]},
                    "duration_ms": 100, "cost_usd": 0.1,
                })

            def run_lc(argv):
                self.assertEqual(argv[1], "guidance-dir")
                return str(repo) + "\n"

            before = {p.name for p in Path(tmp).iterdir()}
            args = gr.build_parser().parse_args(["report", "--out", str(out)])
            gr.cmd_report(args, run_lc, DirGit())
            after = {p.name for p in Path(tmp).iterdir()}
            self.assertEqual(before, after)
            return (out / "report.md").read_text()

    def spawns(self):
        return [
            spawn("s1", "p1", delivered=("A", "B"), skipped=("S",), cited=("A",)),
            spawn("s2", "p2", delivered=("A",), cited=("A",)),
        ]

    def test_sections_in_order_and_exclusions_counted(self):
        text = self.run_report(["A"], self.spawns())
        positions = [text.index("## " + s) for s in gr.SECTIONS]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("pairs excluded (entry unresolved or not stable): 1", text)

    def test_all_resolved(self):
        text = self.run_report(["A", "B"], self.spawns())
        self.assertIn("pairs excluded (entry unresolved or not stable): 0", text)

    def test_none_resolved(self):
        text = self.run_report([], self.spawns())
        self.assertIn("pairs excluded (entry unresolved or not stable): 3", text)
        self.assertIn("## Verdict", text)

    def test_skipped_only_yields_no_scored_pairs(self):
        text = self.run_report(
            ["S"], [spawn("s1", "p1", delivered=("A",), skipped=("S",), cited=())]
        )
        self.assertIn("delivered pairs scored: 0", text)
        self.assertIn("1 scored", text)


class ProjectedPairsTest(unittest.TestCase):
    def test_skipped_never_enter_pairs(self):
        spawns = [spawn("s1", "p", delivered=(), skipped=("S",))]
        pairs, excluded, skipped = gr.build_pairs(spawns, {"s1": {"S": 0.9}}, {"S": 10})
        self.assertEqual(pairs, [])
        self.assertEqual(excluded, 0)
        self.assertEqual(len(skipped), 1)


if __name__ == "__main__":
    unittest.main()
