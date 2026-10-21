import argparse
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "mutation_baseline.txt"
SOURCE_GLOB = "lightcycle/domain/**/*.py"
RUN_COMMAND = ["uv", "run", "mutmut", "run", "--max-children", "4"]
RESULTS_COMMAND = ["uv", "run", "mutmut", "results", "--all", "true"]
KILLED = "killed"
EXCLUDED = ("skipped", "not checked", "check was interrupted by user", "caught by type check")
RUN_TIMEOUT = 7200
QUERY_TIMEOUT = 120

USAGE = "uv run python scripts/mutation_ratchet.py {measure,check} [options]"


def all_modules(root=ROOT):
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.glob(SOURCE_GLOB)
        if path.name != "__init__.py"
    )


def mutant_prefix(module_path):
    return module_path.removesuffix(".py").replace("/", ".")


def score(killed, total):
    value = Decimal(100 * killed) / Decimal(total)
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def format_baseline(scores):
    return "".join(f"{module}: {scores[module]}\n" for module in sorted(scores))


def parse_baseline(text):
    scores = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        module, _, value = line.rpartition(": ")
        scores[module] = Decimal(value)
    return scores


def parse_results(text, prefixes):
    counts = {}
    excluded = 0
    for line in text.splitlines():
        name, sep, status = line.strip().rpartition(": ")
        if not sep:
            continue
        module = name.rsplit(".", 1)[0]
        if module not in prefixes:
            continue
        if status in EXCLUDED:
            excluded += 1
            continue
        killed, total = counts.get(prefixes[module], (0, 0))
        counts[prefixes[module]] = (killed + (status == KILLED), total + 1)
    return counts, excluded


def scores_from_counts(counts):
    return {module: score(k, t) for module, (k, t) in counts.items() if t}


def select_modules(changed_files, baseline_modules):
    selected = [path for path in changed_files if path in baseline_modules]
    unresolved = [path for path in changed_files if path not in baseline_modules]
    return sorted(selected), unresolved


def below_baseline(current, baseline):
    return sorted(
        module
        for module, value in current.items()
        if module in baseline and value < baseline[module]
    )


def run_mutants(modules):
    globs = [f"{mutant_prefix(module)}.*" for module in modules]
    subprocess.run(RUN_COMMAND + globs, cwd=ROOT, timeout=RUN_TIMEOUT)
    done = subprocess.run(
        RESULTS_COMMAND, cwd=ROOT, timeout=QUERY_TIMEOUT, capture_output=True, text=True
    )
    if done.returncode != 0:
        raise SystemExit(f"could not read results: {done.stderr.strip()}")
    prefixes = {mutant_prefix(module): module for module in modules}
    return parse_results(done.stdout, prefixes)


def measure_modules(modules):
    counts, excluded = run_mutants(modules)
    print(f"excluded from totals (skipped or not checked): {excluded}")
    for module in modules:
        killed, total = counts.get(module, (0, 0))
        if not total:
            print(f"{module}: no mutants")
            continue
        print(f"{module}: {killed}/{total} {score(killed, total)}%")
    return scores_from_counts(counts)


def changed_files(base_ref):
    done = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=ROOT,
        timeout=QUERY_TIMEOUT,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise SystemExit(f"git diff failed: {done.stderr.strip()}")
    return done.stdout.split()


def cmd_measure(args):
    modules = args.modules or all_modules()
    current = measure_modules(modules)
    if args.write_baseline:
        BASELINE.write_text(format_baseline(current))
        print(f"wrote {BASELINE.relative_to(ROOT)} ({len(current)} modules)")
    return 0


def cmd_check(args):
    baseline = parse_baseline(BASELINE.read_text())
    modules = sorted(baseline)
    if args.scoped:
        modules, unresolved = select_modules(changed_files(args.scoped), set(baseline))
        for path in unresolved:
            print(f"{path}: not in baseline")
        if not modules:
            print("no baseline module touched")
            return 0
    current = measure_modules(modules)
    failed = below_baseline(current, baseline)
    for module in modules:
        if module not in current:
            continue
        verdict = "FAIL" if module in failed else "ok"
        print(f"{verdict} {module}: {current[module]} (baseline {baseline[module]})")
    return 1 if failed else 0


def build_parser():
    parser = argparse.ArgumentParser(prog="mutation_ratchet.py", usage=USAGE)
    sub = parser.add_subparsers(dest="command", required=True)
    measure = sub.add_parser("measure")
    measure.add_argument("--modules", nargs="+")
    measure.add_argument("--write-baseline", action="store_true")
    measure.set_defaults(handler=cmd_measure)
    check = sub.add_parser("check")
    check.add_argument("--scoped", metavar="BASE_REF")
    check.set_defaults(handler=cmd_check)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
