import argparse
import ast
import io
import json
import re
import statistics
import subprocess
import sys
import time
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.mutation_ratchet import (
    EXCLUDED,
    KILLED,
    QUERY_TIMEOUT,
    ROOT,
    all_modules,
    mutant_prefix,
    parse_results,
    score,
)

STATS_FILE = ROOT / "mutants" / "mutmut-stats.json"
MUTMUT = [sys.executable, "-m", "mutmut"]
RESULTS_COMMAND = MUTMUT + ["results", "--all", "true"]
RUN_COMMAND = MUTMUT + ["run"]
STDERR_TAIL_LINES = 20
RUN_TIMEOUT = 7200
SHOW_TIMEOUT = 120
COVERAGE_TIMEOUT = 3600
COVERED_THRESHOLD = 0.8
MUTANT_SUFFIX = re.compile(r"__mutmut_\d+$")
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")
STRING_TOKENS = {tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", tokenize.STRING)}
FORMAT_CALLS = {"join", "format"}
PRUNES = ("none", "strings", "formatting", "both")

USAGE = (
    "uv run python scripts/mutation_report.py "
    "{rows,crap,join,cost,prune,run} [options]"
)


def split_mutant_name(name):
    base = MUTANT_SUFFIX.sub("", name)
    module, _, tail = base.rpartition(".")
    if tail.startswith("xǁ"):
        _, cls, method = tail.split("ǁ")
        return module, f"{cls}.{method}"
    if tail.startswith("x_"):
        return module, tail[2:]
    return module, tail


def module_path(module):
    return module.replace(".", "/") + ".py"


def parse_show(text):
    lines = text.splitlines()
    head, _, status = lines[0].removeprefix("# ").rpartition(": ")
    module, function = split_mutant_name(head)
    file = ""
    line = None
    removed = []
    added = []
    old_line = 0
    in_hunk = False
    for raw in lines[1:]:
        if raw.startswith("--- "):
            file = raw[4:].strip()
            continue
        if raw.startswith("+++ "):
            continue
        match = HUNK.match(raw)
        if match:
            old_line = int(match.group(1))
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith("-"):
            if line is None:
                line = old_line
            removed.append(raw[1:].strip())
            old_line += 1
        elif raw.startswith("+"):
            added.append(raw[1:].strip())
        else:
            old_line += 1
    return {
        "name": head,
        "status": status,
        "file": file,
        "module": module,
        "function": function,
        "line": line,
        "removed": "\n".join(removed),
        "added": "\n".join(added),
    }


def normalised_tokens(line):
    kept = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(line.strip() + "\n").readline):
            if token.type in (tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER):
                continue
            kept.append("<str>" if token.type in STRING_TOKENS else token.string)
    except (tokenize.TokenError, IndentationError):
        pass
    return kept


def is_string_only(removed, added):
    left = normalised_tokens(removed)
    right = normalised_tokens(added)
    return bool(left) and left == right


def is_formatting_return(node):
    value = node.value
    if isinstance(value, ast.JoinedStr):
        return True
    if isinstance(value, ast.Constant):
        return isinstance(value.value, str)
    if isinstance(value, ast.Call):
        return isinstance(value.func, ast.Attribute) and value.func.attr in FORMAT_CALLS
    if isinstance(value, ast.BinOp):
        return (
            isinstance(value.op, ast.Mod)
            and isinstance(value.left, ast.Constant)
            and isinstance(value.left.value, str)
        )
    return False


def own_nodes(function_node):
    stack = list(function_node.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            stack.append(child)


def is_formatting_function(source):
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not functions:
        return False
    returns = [n for n in own_nodes(functions[0]) if isinstance(n, ast.Return)]
    if not returns:
        return False
    return all(r.value is not None and is_formatting_return(r) for r in returns)


def cyclomatic(function_node):
    total = 1
    for node in own_nodes(function_node):
        if isinstance(
            node,
            (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.match_case),
        ):
            total += 1
        elif isinstance(node, ast.comprehension):
            total += 1 + len(node.ifs)
        elif isinstance(node, ast.BoolOp):
            total += len(node.values) - 1
    return total


def function_coverage(executed, missing, start, end):
    hit = sum(1 for n in executed if start <= n <= end)
    lost = sum(1 for n in missing if start <= n <= end)
    if hit + lost == 0:
        return 1.0
    return hit / (hit + lost)


def crap(complexity, coverage):
    return complexity**2 * (1 - coverage) ** 3 + complexity


def module_functions(tree):
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append((f"{node.name}.{child.name}", child))
    return found


def crap_rows(path, source, executed, missing):
    rows = []
    for key, node in module_functions(ast.parse(source)):
        complexity = cyclomatic(node)
        coverage = function_coverage(executed, missing, node.lineno, node.end_lineno)
        rows.append(
            {
                "path": path,
                "function": key,
                "line": node.lineno,
                "complexity": complexity,
                "coverage": coverage,
                "crap": crap(complexity, coverage),
            }
        )
    return rows


def is_survivor(row):
    return row["status"] != KILLED and row["status"] not in EXCLUDED


def join(crap_table, mutant_rows):
    by_key = {(r["path"], r["function"]): r for r in crap_table}
    joined = []
    unjoined = []
    for row in mutant_rows:
        found = by_key.get((module_path(row["module"]), row["function"]))
        if found is None:
            unjoined.append(row)
            continue
        joined.append({**row, **{k: found[k] for k in ("complexity", "coverage", "crap")}})
    return joined, unjoined


def covered_but_not_checked(joined, threshold=COVERED_THRESHOLD):
    grouped = {}
    for row in joined:
        if row["coverage"] >= threshold and is_survivor(row):
            key = (module_path(row["module"]), row["function"])
            grouped.setdefault(key, []).append(row)
    return grouped


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def tests_per_mutant(names, tests_by_function):
    return {
        name: len(tests_by_function.get(MUTANT_SUFFIX.sub("", name), ())) for name in names
    }


def distribution(counts):
    values = list(counts.values())
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    return {
        "min": min(values),
        "median": statistics.median(values),
        "p90": percentile(values, 0.9),
        "p99": percentile(values, 0.99),
        "max": max(values),
        "top5": top,
    }


def slowest_domain_tests(stats, count=10):
    covering = set()
    for tests in stats["tests_by_mangled_function_name"].values():
        covering.update(tests)
    durations = {t: d for t, d in stats["duration_by_test"].items() if t in covering}
    return sorted(durations.items(), key=lambda item: (-item[1], item[0]))[:count]


def parse_all_results(text):
    pairs = []
    for line in text.splitlines():
        name, sep, status = line.strip().rpartition(": ")
        if sep:
            pairs.append((name, status))
    return pairs


def run_command(command, timeout):
    done = subprocess.run(command, cwd=ROOT, timeout=timeout, capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"{' '.join(command)} failed: {done.stderr.strip()}")
    return done.stdout


def read_statuses():
    return parse_all_results(run_command(RESULTS_COMMAND, QUERY_TIMEOUT))


def show_row(name):
    return parse_show(run_command(MUTMUT + ["show", name], SHOW_TIMEOUT))


def load_stats():
    return json.loads(STATS_FILE.read_text())


def function_start(source, function):
    for key, node in module_functions(ast.parse(source)):
        if key == function:
            return min([node.lineno] + [d.lineno for d in node.decorator_list])
    return None


def with_file_line(row, source):
    start = function_start(source, row["function"])
    if start is None or row["line"] is None:
        return row
    return {**row, "line": start + row["line"] - 1}


def build_rows(statuses, stats):
    counts = tests_per_mutant([n for n, s in statuses if s != KILLED], stats["tests_by_mangled_function_name"])
    rows = []
    for name, status in statuses:
        if status == KILLED:
            continue
        row = show_row(name)
        row["status"] = status
        row["tests"] = counts[name]
        path = ROOT / module_path(row["module"])
        rows.append(with_file_line(row, path.read_text()) if path.exists() else row)
    return rows


def function_source(module, function):
    path = ROOT / module_path(module)
    source = path.read_text()
    for key, node in module_functions(ast.parse(source)):
        if key == function:
            return ast.get_source_segment(source, node)
    return None


def pruned_by(row, mode):
    if mode in ("strings", "both") and is_string_only(row["removed"], row["added"]):
        return True
    if mode in ("formatting", "both"):
        source = function_source(row["module"], row["function"])
        if source is not None and is_formatting_function(source):
            return True
    return False


def prune_names(statuses, mode):
    if mode == "none":
        return [n for n, _ in statuses], []
    kept = []
    dropped = []
    for name, _ in statuses:
        (dropped if pruned_by(show_row(name), mode) else kept).append(name)
    return kept, dropped


def coverage_table(coverage_json):
    data = json.loads(Path(coverage_json).read_text())
    table = []
    for module in all_modules():
        entry = data["files"].get(module)
        if entry is None:
            continue
        source = (ROOT / module).read_text()
        table.extend(crap_rows(module, source, entry["executed_lines"], entry["missing_lines"]))
    return table


def cmd_rows(args):
    rows = build_rows(read_statuses(), load_stats())
    Path(args.out).write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


def cmd_crap(args):
    done = subprocess.run(
        ["uv", "run", "coverage", "run", "--data-file", args.data,
         "-m", "pytest", "tests/unit", "-p", "no:xdist", "-q"],
        cwd=ROOT,
        timeout=COVERAGE_TIMEOUT,
    )
    if done.returncode != 0:
        raise SystemExit("unit suite failed under coverage")
    run_command(
        ["uv", "run", "coverage", "json", "--data-file", args.data,
         "--include", "lightcycle/domain/*", "-o", args.json],
        QUERY_TIMEOUT,
    )
    table = coverage_table(args.json)
    Path(args.out).write_text(json.dumps(table, indent=1))
    print(f"wrote {len(table)} functions to {args.out}")
    return 0


def cmd_join(args):
    table = json.loads(Path(args.crap).read_text())
    rows = json.loads(Path(args.rows).read_text())
    joined, unjoined = join(table, rows)
    top = sorted(r["crap"] for r in table)
    cut = top[int(len(top) * 0.9)] if top else 0
    survivors = [r for r in joined if is_survivor(r)]
    high = [r for r in survivors if r["crap"] >= cut]
    print(f"joined: {len(joined)}, unjoined: {len(unjoined)}")
    print(f"functions: {len(table)}, top-decile CRAP cut: {cut:.2f}")
    print(f"survivors in top decile: {len(high)} of {len(survivors)}")
    for (path, function), group in sorted(covered_but_not_checked(joined).items()):
        print(f"covered but not checked: {path} {function} x{len(group)}")
    Path(args.out).write_text(json.dumps({"joined": joined, "unjoined": unjoined}, indent=1))
    return 0


def cmd_cost(args):
    stats = load_stats()
    names = [n for n, _ in read_statuses()]
    dist = distribution(tests_per_mutant(names, stats["tests_by_mangled_function_name"]))
    print(json.dumps(dist, indent=1, ensure_ascii=False))
    for test, seconds in slowest_domain_tests(stats):
        print(f"{seconds:.3f}s {test}")
    return 0


def cmd_prune(args):
    rows = json.loads(Path(args.rows).read_text())
    for mode in PRUNES[1:]:
        dropped = [r for r in rows if pruned_by(r, mode)]
        print(f"{mode}: removes {len(dropped)} of {len(rows)} non-killed rows")
    return 0


def cmd_run(args):
    statuses = read_statuses()
    prefixes = {mutant_prefix(m): m for m in args.modules}
    wanted = [
        (n, s)
        for n, s in statuses
        if split_mutant_name(n)[0] in prefixes
    ]
    kept, dropped = prune_names(wanted, args.prune)
    print(f"mutants: {len(wanted)}, pruned: {len(dropped)}, running: {len(kept)}")
    started = time.monotonic()
    done = subprocess.run(
        RUN_COMMAND + ["--max-children", str(args.max_children)] + kept,
        cwd=ROOT,
        timeout=RUN_TIMEOUT,
        stderr=subprocess.PIPE,
        text=True,
    )
    if done.returncode != 0:
        tail = "\n".join(done.stderr.strip().splitlines()[-STDERR_TAIL_LINES:])
        print(f"mutmut run failed with exit code {done.returncode}: {tail}", file=sys.stderr)
        return 1
    print(f"mutmut run wall seconds: {time.monotonic() - started:.0f}")
    ran = set(kept)
    results = "\n".join(f"{n}: {st}" for n, st in read_statuses() if n in ran)
    Path(args.results_out).write_text(results)
    counts, excluded, timeouts = parse_results(results, prefixes)
    print(f"excluded: {excluded}, of which timeout: {timeouts}")
    for module in args.modules:
        killed, total = counts.get(module, (0, 0))
        print(f"{module}: {killed}/{total} {score(killed, total) if total else 'no mutants'}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="mutation_report.py", usage=USAGE)
    sub = parser.add_subparsers(dest="command", required=True)
    rows = sub.add_parser("rows")
    rows.add_argument("--out", required=True)
    rows.set_defaults(handler=cmd_rows)
    crap_cmd = sub.add_parser("crap")
    crap_cmd.add_argument("--data", required=True)
    crap_cmd.add_argument("--json", required=True)
    crap_cmd.add_argument("--out", required=True)
    crap_cmd.set_defaults(handler=cmd_crap)
    join_cmd = sub.add_parser("join")
    join_cmd.add_argument("--crap", required=True)
    join_cmd.add_argument("--rows", required=True)
    join_cmd.add_argument("--out", required=True)
    join_cmd.set_defaults(handler=cmd_join)
    sub.add_parser("cost").set_defaults(handler=cmd_cost)
    prune = sub.add_parser("prune")
    prune.add_argument("--rows", required=True)
    prune.set_defaults(handler=cmd_prune)
    run = sub.add_parser("run")
    run.add_argument("--modules", nargs="+", required=True)
    run.add_argument("--prune", choices=PRUNES, default="none")
    run.add_argument("--max-children", type=int, default=4)
    run.add_argument("--results-out", required=True)
    run.set_defaults(handler=cmd_run)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
