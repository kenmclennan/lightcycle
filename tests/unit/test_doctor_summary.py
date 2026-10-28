import unittest

from lightcycle.domain.health import Problem, doctor_summary, problem_lines


def _findings(category, count, kind=None):
    return [Problem(category, "%s finding %d" % (category, i), kind=kind) for i in range(count)]


class TestDoctorSummary(unittest.TestCase):
    def _singular_and_plural(self, category, singular, plural):
        self.assertEqual(doctor_summary({category: _findings(category, 1)}), "1 " + singular)
        self.assertEqual(doctor_summary({category: _findings(category, 2)}), "2 " + plural)

    def test_store(self):
        self._singular_and_plural("store", "store problem", "store problems")

    def test_pins(self):
        self._singular_and_plural(
            "pins", "item on an old workflow version", "items on an old workflow version")

    def test_contract(self):
        self._singular_and_plural(
            "contract", "workflow the engine rejects", "workflows the engine rejects")

    def test_config(self):
        self._singular_and_plural("config", "config problem", "config problems")

    def test_orphans(self):
        self._singular_and_plural("orphans", "item left behind", "items left behind")

    def test_facets(self):
        self._singular_and_plural("facets", "facet problem", "facet problems")

    def test_guidance(self):
        self._singular_and_plural("guidance", "guidance problem", "guidance problems")

    def test_origin_behind_workflows(self):
        self.assertEqual(
            doctor_summary({"workflows": _findings("workflows", 2, "origin-behind")}),
            "2 workflows out of date")
        self.assertEqual(
            doctor_summary({"workflows": _findings("workflows", 1, "origin-behind")}),
            "1 workflow out of date")

    def test_other_workflow_findings(self):
        self.assertEqual(doctor_summary({"workflows": _findings("workflows", 1)}), "1 workflow problem")
        self.assertEqual(doctor_summary({"workflows": _findings("workflows", 3)}), "3 workflow problems")

    def test_both_workflow_parts_together(self):
        problems = {"workflows": (
            _findings("workflows", 1, "origin-behind") + _findings("workflows", 1))}
        self.assertEqual(doctor_summary(problems), "1 workflow out of date, 1 workflow problem")

    def test_two_categories_join_in_report_order(self):
        problems = {"config": _findings("config", 1), "orphans": _findings("orphans", 3)}
        self.assertEqual(doctor_summary(problems), "1 config problem, 3 items left behind")

    def test_three_parts_collapse_to_a_total(self):
        problems = {
            "store": _findings("store", 1),
            "config": _findings("config", 2),
            "orphans": _findings("orphans", 1),
        }
        self.assertEqual(doctor_summary(problems), "4 problems")

    def test_two_parts_do_not_collapse(self):
        problems = {"store": _findings("store", 1), "config": _findings("config", 2)}
        self.assertEqual(doctor_summary(problems), "1 store problem, 2 config problems")

    def test_the_two_workflow_parts_count_toward_the_collapse(self):
        problems = {
            "workflows": _findings("workflows", 1, "origin-behind") + _findings("workflows", 1),
            "config": _findings("config", 1),
        }
        self.assertEqual(doctor_summary(problems), "3 problems")

    def test_github_alone_is_empty(self):
        self.assertEqual(doctor_summary({"github": _findings("github", 2)}), "")

    def test_no_findings_is_empty(self):
        self.assertEqual(doctor_summary({"store": [], "config": []}), "")

    def test_github_is_not_counted_among_several_categories(self):
        problems = {
            "store": _findings("store", 1),
            "orphans": _findings("orphans", 1),
            "github": _findings("github", 4),
        }
        self.assertEqual(doctor_summary(problems), "1 store problem, 1 item left behind")


class TestProblemLines(unittest.TestCase):
    def test_a_bare_message(self):
        self.assertEqual(problem_lines([Problem("store", "broken")]), ["  broken"])

    def test_node_id_and_fix(self):
        lines = problem_lines([Problem("store", "broken", node_id="LC-1", fix="lc fix")])
        self.assertEqual(lines, ["  broken (LC-1)", "    fix: lc fix"])

    def test_no_problems_is_empty(self):
        self.assertEqual(problem_lines([]), [])
