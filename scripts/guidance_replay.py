import argparse
import datetime
import json
import math
import random
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROMPT_VERSION = "v1"
LC_VERBS = ("worklog", "trace", "show", "peek", "guidance-dir", "guidance")
LC_TIMEOUT = 120
CLAUDE_TIMEOUT = 300
BRIEF_LIMIT = 6000
STEP_LIMIT = 6000
EXCERPT_LIMIT = 400
DISAGREEMENT_LIMIT = 10
THRESHOLDS = tuple(round(i / 10, 1) for i in range(1, 10))
HIGH_MIN_DELIVERIES = 10
HIGH_MIN_RATE = 0.5
RECALL_FLOOR = 0.90
SAVED_BAR = 0.20
DEFAULT_THRESHOLD = 0.5
DEFAULT_OUT = ".guidance-replay"
DEFAULT_N = 240
DEFAULT_DAYS = 14
MIN_PROJECTS = 3
WORKLOG_LINE = re.compile(r"^([A-Z][A-Z0-9]*-\d+)\s")

PROMPT = (
    "You judge which guidance entries a coding agent needs before it starts a step. "
    "You are given the item brief, the step the agent will perform, and candidate "
    "guidance entries, each as an id and a body. For every candidate id, give the "
    "probability between 0 and 1 that an agent doing this step on this brief would need "
    "that entry to avoid a mistake. Reply with only a JSON object mapping every candidate "
    "id to its probability, with no other keys and no prose."
)

SECTIONS = (
    "Verdict",
    "Method",
    "Threshold table",
    "Per-entry table",
    "Skipped entries",
    "Disagreements",
    "Cost and latency",
    "Limitations",
)

USAGE = "uv run python scripts/guidance_replay.py {sample,score,report,run} [options]"


class ReplayError(Exception):
    pass


def lc_argv(verb, *args):
    if verb not in LC_VERBS:
        raise ReplayError("verb %s is not read-only" % verb)
    return ["lc", verb, *args]


def default_run_lc(argv):
    proc = subprocess.run(
        argv, capture_output=True, text=True, timeout=LC_TIMEOUT, check=False
    )
    if proc.returncode != 0:
        raise ReplayError("%s failed: %s" % (" ".join(argv), proc.stderr.strip()))
    return proc.stdout


def default_run_claude(argv, prompt, cwd):
    proc = subprocess.run(
        argv, input=prompt, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
        cwd=cwd, check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def ids_of(artifacts, name):
    for a in artifacts:
        if a.get("type") == name:
            return [x.strip() for x in a.get("value", "").splitlines() if x.strip()]
    return []


def worklog_items(text):
    items = []
    for line in text.splitlines():
        m = WORKLOG_LINE.match(line)
        if m and m.group(1) not in items:
            items.append(m.group(1))
    return items


def collect_spawns(since, until, run_lc):
    spawns = []
    for item in worklog_items(run_lc(lc_argv("worklog", since, until))):
        trace = json.loads(run_lc(lc_argv("trace", item, "--json")))
        shown = None
        for step in trace.get("steps", []):
            arts = step.get("artifacts", [])
            delivered = ids_of(arts, "guidance-delivered")
            if not delivered:
                continue
            if shown is None:
                shown = json.loads(run_lc(lc_argv("show", item)))
            stage = step.get("step")
            text = run_lc(lc_argv("peek", step["id"], stage))
            spawns.append({
                "step": step["id"],
                "item": item,
                "project": shown.get("repo") or "(no repo)",
                "stage": stage,
                "delivered": delivered,
                "skipped": ids_of(arts, "guidance-skipped"),
                "cited": ids_of(arts, "guidance-cited"),
                "brief": shown.get("description") or "",
                "step_text": text,
            })
    return spawns


def draw(spawns, n, seed):
    projects = {}
    for s in spawns:
        projects.setdefault(s["project"], {}).setdefault(s["stage"], []).append(s)
    if len(projects) < MIN_PROJECTS:
        raise ReplayError(
            "frame has %d projects, need at least %d" % (len(projects), MIN_PROJECTS)
        )
    rng = random.Random(seed)
    queues = {}
    for project in sorted(projects):
        stages = {}
        for stage in sorted(projects[project]):
            pool = sorted(projects[project][stage], key=lambda s: s["step"])
            rng.shuffle(pool)
            stages[stage] = pool
        queues[project] = stages
    picked = []
    cursor = {p: 0 for p in queues}
    while len(picked) < n and any(any(q for q in st.values()) for st in queues.values()):
        for project in sorted(queues):
            stages = sorted(s for s in queues[project] if queues[project][s])
            if not stages or len(picked) >= n:
                continue
            stage = stages[cursor[project] % len(stages)]
            cursor[project] += 1
            picked.append(queues[project][stage].pop())
    return picked


def clip(text, limit):
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", errors="ignore")


def candidates_of(spawn):
    return list(spawn["delivered"]) + [e for e in spawn["skipped"] if e not in spawn["delivered"]]


def build_message(spawn, bodies, seed):
    ids = candidates_of(spawn)
    rng = random.Random("%s:%s" % (seed, spawn["step"]))
    rng.shuffle(ids)
    entries = "\n\n".join("### %s\n%s" % (i, bodies.get(i, "")) for i in ids)
    return "## Brief\n%s\n\n## Step: %s\n%s\n\n## Candidate entries\n%s\n" % (
        clip(spawn["brief"], BRIEF_LIMIT), spawn["stage"],
        clip(spawn["step_text"], STEP_LIMIT), entries,
    )


def valid_reply(reply, ids):
    if not isinstance(reply, dict) or set(reply) != set(ids):
        return False
    for v in reply.values():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
            return False
        if math.isnan(v):
            return False
    return True


def parse_reply(stdout, ids):
    try:
        envelope = json.loads(stdout)
        text = envelope["result"]
        reply = json.loads(text) if isinstance(text, str) else text
    except (ValueError, KeyError, TypeError):
        return None, envelope_meta(stdout)
    meta = envelope_meta(stdout)
    if not valid_reply(reply, ids):
        return None, meta
    return {k: float(v) for k, v in reply.items()}, meta


def envelope_meta(stdout):
    try:
        env = json.loads(stdout)
        usage = env.get("modelUsage") or {}
        return {
            "model_id": next(iter(usage), None),
            "duration_ms": env.get("duration_ms") or 0,
            "cost_usd": env.get("total_cost_usd") or 0.0,
        }
    except (ValueError, AttributeError, TypeError):
        return {"model_id": None, "duration_ms": 0, "cost_usd": 0.0}


def claude_argv():
    return [
        "claude", "-p", "--model", "haiku", "--output-format", "json",
        "--no-session-persistence", "--tools", "", "--system-prompt", PROMPT,
    ]


def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def append_jsonl(path, record):
    with open(path, "a") as fh:
        fh.write(json.dumps(record) + "\n")


def score_spawns(spawns, bodies, out, run_claude, seed, model_hint=None):
    out = Path(out)
    scores_path = out / "scores.jsonl"
    failures_path = out / "failures.jsonl"
    present = {
        (r["step"], r["prompt_version"], r["model_id"]) for r in read_jsonl(scores_path)
    }
    recorded = read_jsonl(scores_path)
    current_model = model_hint or (recorded[-1]["model_id"] if recorded else None)
    scored = failed = calls = 0
    for spawn in spawns:
        if (spawn["step"], PROMPT_VERSION, current_model) in present:
            continue
        ids = candidates_of(spawn)
        message = build_message(spawn, bodies, seed)
        result = None
        for _ in range(2):
            calls += 1
            with tempfile.TemporaryDirectory() as cwd:
                code, stdout, _err = run_claude(claude_argv(), message, cwd)
            if code != 0:
                continue
            probs, meta = parse_reply(stdout, ids)
            if probs is not None:
                result = (probs, meta)
                break
        if result is None:
            failed += 1
            append_jsonl(failures_path, {"step": spawn["step"], "prompt_version": PROMPT_VERSION})
            continue
        probs, meta = result
        append_jsonl(scores_path, {
            "step": spawn["step"], "prompt_version": PROMPT_VERSION,
            "model_id": meta["model_id"], "probs": probs,
            "duration_ms": meta["duration_ms"], "cost_usd": meta["cost_usd"],
        })
        present.add((spawn["step"], PROMPT_VERSION, meta["model_id"]))
        scored += 1
    return {"scored": scored, "failed": failed, "calls": calls}


def metrics_at(pairs, t):
    total = sum(p["size"] for p in pairs)
    dropped = [p for p in pairs if p["prob"] < t]
    kept = [p for p in pairs if p["prob"] >= t]
    cited = [p for p in pairs if p["cited"]]
    cited_kept = [p for p in kept if p["cited"]]
    return {
        "threshold": t,
        "saved": sum(p["size"] for p in dropped) / total if total else 0.0,
        "cited_dropped": len(cited) - len(cited_kept),
        "precision": len(cited_kept) / len(kept) if kept else 0.0,
        "recall": len(cited_kept) / len(cited) if cited else 1.0,
    }


def tags_alone(pairs):
    cited = sum(1 for p in pairs if p["cited"])
    return {"precision": cited / len(pairs) if pairs else 0.0, "recall": 1.0}


def high_citation(pairs):
    counts = {}
    for p in pairs:
        d, c = counts.get(p["entry"], (0, 0))
        counts[p["entry"]] = (d + 1, c + (1 if p["cited"] else 0))
    return sorted(
        e for e, (d, c) in counts.items()
        if d >= HIGH_MIN_DELIVERIES and c / d >= HIGH_MIN_RATE
    )


def evaluate(pairs):
    high = high_citation(pairs)
    rows = []
    for t in THRESHOLDS:
        overall = metrics_at(pairs, t)
        blockers = []
        for e in high:
            sub = [p for p in pairs if p["entry"] == e]
            if metrics_at(sub, t)["recall"] < RECALL_FLOOR:
                blockers.append(e)
        overall["blockers"] = blockers
        overall["qualifies"] = not blockers
        rows.append(overall)
    qualifying = [r for r in rows if r["qualifies"]]
    best = max(qualifying, key=lambda r: r["saved"]) if qualifying else None
    beats = best is not None and best["saved"] >= SAVED_BAR
    return {"high": high, "rows": rows, "best": best, "beats": beats}


def build_pairs(spawns, probs_by_step, sizes):
    pairs, excluded, skipped = [], 0, []
    for spawn in spawns:
        probs = probs_by_step.get(spawn["step"])
        if probs is None:
            continue
        for e in spawn["delivered"]:
            if e not in sizes:
                excluded += 1
                continue
            pairs.append({
                "step": spawn["step"], "stage": spawn["stage"], "entry": e,
                "prob": probs[e], "cited": e in spawn["cited"], "size": sizes[e],
                "brief": spawn["brief"],
            })
        for e in spawn["skipped"]:
            if e in probs and e not in spawn["delivered"]:
                skipped.append({"step": spawn["step"], "entry": e, "prob": probs[e]})
    return pairs, excluded, skipped


def pct(x):
    return "%.1f%%" % (100 * x)


def disagreements(pairs, t, seed):
    rng = random.Random(seed)
    dropped_cited = sorted(
        (p for p in pairs if p["cited"] and p["prob"] < t), key=lambda p: (p["step"], p["entry"])
    )
    kept_uncited = sorted(
        (p for p in pairs if not p["cited"] and p["prob"] >= t), key=lambda p: (p["step"], p["entry"])
    )
    rng.shuffle(dropped_cited)
    rng.shuffle(kept_uncited)
    return dropped_cited[:DISAGREEMENT_LIMIT], kept_uncited[:DISAGREEMENT_LIMIT]


def render_report(ctx):
    pairs = ctx["pairs"]
    ev = evaluate(pairs)
    best = ev["best"]
    headline = best["threshold"] if best else DEFAULT_THRESHOLD
    lines = ["# Guidance replay report", ""]
    lines += ["## Verdict", ""]
    if ev["beats"]:
        lines.append(
            "Haiku beats tags alone at threshold %.1f: it saves %s of delivered bytes with "
            "recall %.2f overall, keeping every high-citation entry at recall of at least %.2f."
            % (best["threshold"], pct(best["saved"]), best["recall"], RECALL_FLOOR)
        )
    elif best is not None:
        lines.append(
            "Haiku does not beat tags alone: the best qualifying threshold is %.1f and it "
            "saves %s of delivered bytes, under the %s bar." % (best["threshold"], pct(best["saved"]), pct(SAVED_BAR))
        )
    else:
        blockers = "; ".join(
            "%.1f: %s" % (r["threshold"], ", ".join(r["blockers"])) for r in ev["rows"]
        )
        lines.append(
            "Haiku does not beat tags alone: no threshold keeps every high-citation entry at "
            "recall of at least %.2f. Blocking entries by threshold - %s." % (RECALL_FLOOR, blockers or "none")
        )
    lines += ["", "## Method", ""]
    lines += [
        "- window: %s" % ctx["window"],
        "- seed: %s" % ctx["seed"],
        "- spawns scored: %d" % ctx["scored"],
        "- projects: %s" % ", ".join(ctx["projects"]),
        "- prompt version: %s" % PROMPT_VERSION,
        "- model id: %s" % ", ".join(ctx["models"]),
        "- delivered pairs scored: %d" % len(pairs),
        "- pairs excluded (entry unresolved or not stable): %d" % ctx["excluded"],
        "- high-citation entries: %s" % (", ".join(ev["high"]) or "none"),
    ]
    lines += ["", "## Threshold table", ""]
    base = tags_alone(pairs)
    lines += [
        "| threshold | bytes saved | cited dropped | precision | recall | qualifies |",
        "| --- | --- | --- | --- | --- | --- |",
        "| tags alone | 0.0%% | 0 | %.2f | %.2f | yes |" % (base["precision"], base["recall"]),
    ]
    for r in ev["rows"]:
        lines.append("| %.1f | %s | %d | %.2f | %.2f | %s |" % (
            r["threshold"], pct(r["saved"]), r["cited_dropped"], r["precision"], r["recall"],
            "yes" if r["qualifies"] else "no"))
    lines += ["", "## Per-entry table", ""]
    lines += [
        "| entry | delivered | cited | bytes | threshold | saved | recall | precision |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in sorted({p["entry"] for p in pairs}):
        sub = [p for p in pairs if p["entry"] == e]
        m = metrics_at(sub, headline)
        lines.append("| %s | %d | %d | %d | %.1f | %s | %.2f | %.2f |" % (
            e, len(sub), sum(1 for p in sub if p["cited"]), sum(p["size"] for p in sub),
            headline, pct(m["saved"]), m["recall"], m["precision"]))
    lines += ["", "## Skipped entries", ""]
    skipped = ctx["skipped"]
    lines.append(
        "Budget-skipped candidates were scored but never enter precision or recall: %d scored." % len(skipped)
    )
    lines += ["", "| threshold | skipped entries rated at or above |", "| --- | --- |"]
    for t in THRESHOLDS:
        lines.append("| %.1f | %d |" % (t, sum(1 for s in skipped if s["prob"] >= t)))
    lines += ["", "## Disagreements", ""]
    dc, ku = disagreements(pairs, headline, ctx["seed"])
    lines.append(
        "At threshold %.1f. An uncited entry that Haiku keeps may have been followed silently, "
        "so the second list is not a count of Haiku errors." % headline
    )
    for title, rows in (("Cited, Haiku would drop", dc), ("Not cited, Haiku keeps", ku)):
        lines += ["", "### %s" % title, ""]
        if not rows:
            lines.append("none")
        for p in rows:
            lines.append("- %s %s p=%.2f: %s" % (
                p["stage"], p["entry"], p["prob"],
                " ".join(clip(p["brief"], EXCERPT_LIMIT).split())))
    lines += ["", "## Cost and latency", ""]
    durations = ctx["durations"]
    costs = ctx["costs"]
    if durations:
        ordered = sorted(durations)
        p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
        lines += [
            "- mean duration per spawn: %.0f ms" % statistics.mean(durations),
            "- 95th percentile duration: %.0f ms" % p95,
            "- mean cost per spawn: %.4f USD" % statistics.mean(costs),
            "- total cost: %.2f USD" % sum(costs),
        ]
    else:
        lines.append("- no scored spawns")
    lines += [
        "- scoring calls including retries: %s" % ctx["calls"],
        "- scoring failures: %d" % ctx["failures"],
    ]
    lines += ["", "## Limitations", ""]
    lines += [
        "- Only shipped items are in the frame; abandoned and still-open items are not.",
        "- Citation is a noisy label: a worker cites only an entry that changed what it did.",
        "- Entry sizes are read from the guidance repo now, and entries whose body changed since "
        "the spawn cannot be detected.",
        "- Skipped entries cannot be cited, so they are not negatives.",
    ]
    return "\n".join(lines) + "\n"


def load_library(run_lc, git=None):
    from lightcycle.application.services.guidance_library import GuidanceLibrary

    if git is None:
        from lightcycle.adapters.gitio import GitAdapter

        git = GitAdapter()
    root = run_lc(lc_argv("guidance-dir")).strip()
    entries, _problems = GuidanceLibrary(git).load(root)
    return {e.id: e for e in entries if e.is_candidate()}


def cmd_sample(a, run_lc):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    until = a.until or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    since = a.since or (
        datetime.date.fromisoformat(until) - datetime.timedelta(days=DEFAULT_DAYS)
    ).isoformat()
    picked = draw(collect_spawns(since, until, run_lc), a.n, a.seed)
    (out / "sample.json").write_text(json.dumps(
        {"since": since, "until": until, "seed": a.seed, "spawns": picked}, indent=2))
    print("sampled %d spawns" % len(picked))
    return 0


def cmd_score(a, run_lc, run_claude):
    out = Path(a.out)
    sample = json.loads((out / "sample.json").read_text())
    library = load_library(run_lc)
    bodies = {i: e.body for i, e in library.items()}
    result = score_spawns(sample["spawns"], bodies, out, run_claude, sample["seed"])
    print("scored %(scored)d, failed %(failed)d, calls %(calls)d" % result)
    (out / "score-run.json").write_text(json.dumps(result))
    return 0


def cmd_report(a, run_lc, git=None):
    out = Path(a.out)
    sample = json.loads((out / "sample.json").read_text())
    library = load_library(run_lc, git)
    sizes = {i: e.size() for i, e in library.items()}
    scores = [r for r in read_jsonl(out / "scores.jsonl") if r["prompt_version"] == PROMPT_VERSION]
    probs_by_step = {r["step"]: r["probs"] for r in scores}
    spawns = [s for s in sample["spawns"] if s["step"] in probs_by_step]
    pairs, excluded, skipped = build_pairs(spawns, probs_by_step, sizes)
    failures = len(read_jsonl(out / "failures.jsonl"))
    run_info = {}
    if (out / "score-run.json").exists():
        run_info = json.loads((out / "score-run.json").read_text())
    ctx = {
        "pairs": pairs, "excluded": excluded, "skipped": skipped,
        "window": "%s to %s" % (sample["since"], sample["until"]),
        "seed": sample["seed"], "scored": len(spawns),
        "projects": sorted({s["project"] for s in spawns}),
        "models": sorted({r["model_id"] or "unknown" for r in scores}),
        "durations": [r["duration_ms"] for r in scores],
        "costs": [r["cost_usd"] for r in scores],
        "calls": run_info.get("calls", "unknown"),
        "failures": failures,
    }
    (out / "report.md").write_text(render_report(ctx))
    print("wrote %s" % (out / "report.md"))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="guidance_replay.py", usage=USAGE)
    p.add_argument("command", choices=("sample", "score", "report", "run"))
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--n", type=int, default=DEFAULT_N)
    p.add_argument("--seed", type=int, default=0)
    return p


def main(argv=None, run_lc=default_run_lc, run_claude=default_run_claude):
    a = build_parser().parse_args(argv)
    try:
        if a.command in ("sample", "run"):
            cmd_sample(a, run_lc)
        if a.command in ("score", "run"):
            cmd_score(a, run_lc, run_claude)
        if a.command in ("report", "run"):
            cmd_report(a, run_lc)
    except ReplayError as e:
        sys.stderr.write("guidance_replay: %s\n" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
