import ast
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import mutation_ratchet as mr
from scripts import mutation_report as rp

ROOT = Path(__file__).resolve().parents[2]

SHOW = """# pkg.m.x_label__mutmut_1: survived
--- pkg/m.py
+++ pkg/m.py
@@ -1,4 +1,4 @@
 def label(n):
-    if n > 1:
+    if n >= 1:
         return "many"
     return "one"
"""


def function_node(source):
    return ast.parse(source).body[0]


class TestParseShow(unittest.TestCase):
    def test_function_mutant(self):
        row = rp.parse_show(SHOW)
        self.assertEqual(row["name"], "pkg.m.x_label__mutmut_1")
        self.assertEqual(row["status"], "survived")
        self.assertEqual(row["file"], "pkg/m.py")
        self.assertEqual(row["line"], 2)
        self.assertEqual(row["removed"], "if n > 1:")
        self.assertEqual(row["added"], "if n >= 1:")
        self.assertEqual(row["function"], "label")
        self.assertEqual(row["module"], "pkg.m")

    def test_method_mutant_name_gives_class_and_method(self):
        text = SHOW.replace("pkg.m.x_label__mutmut_1", "lightcycle.domain.runs.phase_run.xǁPhaseRunǁas_dict__mutmut_1")
        row = rp.parse_show(text)
        self.assertEqual(row["function"], "PhaseRun.as_dict")
        self.assertEqual(row["module"], "lightcycle.domain.runs.phase_run")

    def test_forwarded_note_function_key(self):
        module, function = rp.split_mutant_name(
            "lightcycle.domain.work.forwarded_note.x_parse_forwarded__mutmut_1"
        )
        self.assertEqual(module, "lightcycle.domain.work.forwarded_note")
        self.assertEqual(function, "parse_forwarded")


class TestFileLine(unittest.TestCase):
    SOURCE = "import os\n\n\ndef other():\n    return 1\n\n\ndef label(n):\n    if n > 1:\n        return 1\n    return 2\n"

    def test_function_below_line_one_gives_real_file_line(self):
        row = rp.with_file_line(rp.parse_show(SHOW), self.SOURCE)
        self.assertEqual(self.SOURCE.splitlines()[row["line"] - 1].strip(), "if n > 1:")
        self.assertEqual(row["line"], 9)

    def test_method_uses_class_qualified_start(self):
        source = "class A:\n    x = 1\n\n    def m(self):\n        return 1\n"
        row = {"function": "A.m", "line": 2}
        self.assertEqual(rp.with_file_line(row, source)["line"], 5)

    def test_decorated_function_starts_at_its_decorator(self):
        source = "class A:\n    @staticmethod\n    def m(n):\n        return n\n"
        row = {"function": "A.m", "line": 3}
        self.assertEqual(rp.with_file_line(row, source)["line"], 4)

    def test_unknown_function_keeps_row(self):
        row = {"function": "gone", "line": 2}
        self.assertEqual(rp.with_file_line(row, self.SOURCE), row)


class TestStringOnly(unittest.TestCase):
    def test_string_change_is_string_only(self):
        self.assertTrue(rp.is_string_only('return "many"', 'return "XXmanyXX"'))

    def test_operator_change_is_not(self):
        self.assertFalse(rp.is_string_only("if n > 1:", "if n >= 1:"))

    def test_empty_line_is_not(self):
        self.assertFalse(rp.is_string_only("", ""))


class TestFormattingFunction(unittest.TestCase):
    def test_fstring_return(self):
        self.assertTrue(rp.is_formatting_function('def f(x):\n    return f"{x}"\n'))

    def test_join_return(self):
        self.assertTrue(rp.is_formatting_function('def f(x):\n    return ", ".join(x)\n'))

    def test_arithmetic_return_is_not(self):
        self.assertFalse(rp.is_formatting_function("def f(x):\n    return x + 1\n"))

    def test_one_non_format_return_is_not(self):
        source = 'def f(x):\n    if x:\n        return "a"\n    return x\n'
        self.assertFalse(rp.is_formatting_function(source))


class TestCyclomatic(unittest.TestCase):
    def test_if_and_for_count(self):
        node = function_node("def f(a, b, xs):\n    if a and b:\n        for x in xs:\n            pass\n")
        self.assertEqual(rp.cyclomatic(node), 4)

    def test_straight_line_is_one(self):
        self.assertEqual(rp.cyclomatic(function_node("def f():\n    return 1\n")), 1)

    def test_nested_def_adds_nothing_to_its_parent(self):
        source = "def f(a):\n    def g(b):\n        if b:\n            return 1\n    return g\n"
        self.assertEqual(rp.cyclomatic(function_node(source)), 1)

    def test_comprehension_filter_and_conditional_expression(self):
        node = function_node("def f(xs):\n    return [x if x else 0 for x in xs if x]\n")
        self.assertEqual(rp.cyclomatic(node), 4)

    def test_except_handler_and_while(self):
        source = "def f():\n    while True:\n        try:\n            pass\n        except Exception:\n            pass\n"
        self.assertEqual(rp.cyclomatic(function_node(source)), 3)


class TestCoverageAndCrap(unittest.TestCase):
    def test_function_coverage_counts_only_lines_inside_range(self):
        self.assertEqual(rp.function_coverage([1, 2, 10], [3, 20], 1, 4), 2 / 3)

    def test_function_without_measured_lines_is_fully_covered(self):
        self.assertEqual(rp.function_coverage([1], [2], 5, 9), 1.0)

    def test_crap_values(self):
        self.assertEqual(rp.crap(4, 0.5), 6.0)
        self.assertEqual(rp.crap(4, 1.0), 4.0)
        self.assertEqual(rp.crap(4, 0.0), 20.0)
        self.assertEqual(rp.crap(1, 0.0), 2.0)


def mutant(name, function, status="survived"):
    return {"name": name, "module": "pkg.m", "function": function, "status": status}


TABLE = [
    {"path": "pkg/m.py", "function": "a", "complexity": 2, "coverage": 0.9, "crap": 2.0},
    {"path": "pkg/m.py", "function": "B.c", "complexity": 3, "coverage": 0.5, "crap": 4.0},
]


class TestJoin(unittest.TestCase):
    def test_all_resolved(self):
        joined, unjoined = rp.join(TABLE, [mutant("n1", "a"), mutant("n2", "B.c")])
        self.assertEqual(len(joined), 2)
        self.assertEqual(unjoined, [])

    def test_none_resolved(self):
        joined, unjoined = rp.join(TABLE, [mutant("n1", "zzz")])
        self.assertEqual(joined, [])
        self.assertEqual(len(unjoined), 1)

    def test_mixed_resolved_and_unresolved(self):
        rows = [mutant("n1", "a"), mutant("n2", "B.c"), mutant("n3", "gone")]
        joined, unjoined = rp.join(TABLE, rows)
        self.assertEqual([r["name"] for r in joined], ["n1", "n2"])
        self.assertEqual([r["name"] for r in unjoined], ["n3"])
        self.assertEqual(joined[0]["crap"], 2.0)

    def test_covered_but_not_checked_needs_coverage_and_a_real_survivor(self):
        rows = [mutant("n1", "a"), mutant("n2", "B.c"), mutant("n3", "a", "timeout")]
        joined, _ = rp.join(TABLE, rows)
        self.assertEqual(list(rp.covered_but_not_checked(joined)), [("pkg/m.py", "a")])


class TestCost(unittest.TestCase):
    def test_distribution_and_top(self):
        counts = {"a": 1, "b": 3, "c": 5}
        dist = rp.distribution(counts)
        self.assertEqual((dist["min"], dist["median"], dist["max"]), (1, 3, 5))
        self.assertEqual(dist["top5"][0], ("c", 5))

    def test_tests_per_mutant_strips_the_mutant_suffix(self):
        counts = rp.tests_per_mutant(["pkg.m.x_a__mutmut_1", "pkg.m.x_z__mutmut_2"], {"pkg.m.x_a": ["t1", "t2"]})
        self.assertEqual(counts, {"pkg.m.x_a__mutmut_1": 2, "pkg.m.x_z__mutmut_2": 0})

    def test_slowest_tests_only_those_covering_a_function(self):
        stats = {
            "tests_by_mangled_function_name": {"f": ["t1"]},
            "duration_by_test": {"t1": 0.5, "t2": 9.0},
        }
        self.assertEqual(rp.slowest_domain_tests(stats), [("t1", 0.5)])


class TestRealDomainContent(unittest.TestCase):
    def test_every_function_in_every_domain_module_has_a_complexity(self):
        modules = mr.all_modules()
        seen = 0
        for module in modules:
            for _, node in rp.module_functions(ast.parse((ROOT / module).read_text())):
                self.assertGreaterEqual(rp.cyclomatic(node), 1, module)
            seen += 1
        self.assertEqual(seen, len(modules))
        self.assertGreater(seen, 100)


class TestCmdRun(unittest.TestCase):
    def run_with(self, command):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "results.txt"
            argv = ["run", "--modules", "pkg/m.py", "--results-out", str(out)]
            err = io.StringIO()
            with (
                mock.patch.object(rp, "RUN_COMMAND", command),
                mock.patch.object(rp, "read_statuses", return_value=[("pkg.m.x_f__mutmut_1", "killed")]),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(err),
            ):
                rc = rp.main(argv)
            return rc, err.getvalue(), out.exists()

    def test_failing_mutmut_run_exits_nonzero_and_writes_no_results(self):
        command = [sys.executable, "-c", "import sys; sys.stderr.write('setup aborted'); sys.exit(1)"]
        rc, err, written = self.run_with(command)
        self.assertEqual(rc, 1)
        self.assertIn("mutmut run failed with exit code 1", err)
        self.assertIn("setup aborted", err)
        self.assertFalse(written)

    def test_successful_mutmut_run_writes_results(self):
        rc, _, written = self.run_with([sys.executable, "-c", "pass"])
        self.assertEqual(rc, 0)
        self.assertTrue(written)


class TestCmdRunSelection(unittest.TestCase):
    NAMES = [("pkg.m.x_f__mutmut_1", "not checked"), ("pkg.m.x_f__mutmut_2", "not checked")]

    def run_with(self, statuses_by_call):
        calls = []
        statuses = iter(statuses_by_call)

        def fake_run(command, **kwargs):
            calls.append(command)
            return mock.Mock(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "results.txt"
            argv = ["run", "--modules", "pkg/m.py", "--results-out", str(out)]
            err = io.StringIO()
            with (
                mock.patch.object(rp, "RUN_COMMAND", ["mutmut-run"]),
                mock.patch.object(rp, "GENERATE_COMMAND", ["mutmut-generate"]),
                mock.patch.object(rp, "read_statuses", side_effect=lambda: next(statuses)),
                mock.patch.object(rp.subprocess, "run", side_effect=fake_run),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(err),
            ):
                rc = rp.main(argv)
        return rc, err.getvalue(), calls

    def test_generate_runs_before_selection_when_no_statuses_exist(self):
        rc, _, calls = self.run_with([[], self.NAMES, self.NAMES])
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], ["mutmut-generate"])
        self.assertEqual(calls[1][0], "mutmut-run")

    def test_generate_is_skipped_when_statuses_already_exist(self):
        rc, _, calls = self.run_with([self.NAMES, self.NAMES])
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in calls], ["mutmut-run"])

    def test_empty_selection_after_generate_exits_nonzero_without_running(self):
        rc, err, calls = self.run_with([[], []])
        self.assertEqual(rc, 1)
        self.assertIn("pkg/m.py", err)
        self.assertEqual(calls, [["mutmut-generate"]])

    def test_run_receives_exactly_the_selected_names(self):
        _, _, calls = self.run_with([self.NAMES, self.NAMES])
        self.assertEqual(calls[0][-2:], [n for n, _ in self.NAMES])
        self.assertEqual(calls[0][:1], ["mutmut-run"])
