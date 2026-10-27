import datetime
import types
import unittest

from lightcycle.adapters.tui.views.report_markdown import report_markdown
from lightcycle.domain.money import Cost
from lightcycle.application.work.report import ProjectReport, ReportResponse
from lightcycle.domain.work.summary_split import split_summary


def _cost(usd):
    return types.SimpleNamespace(cost_usd=Cost.from_usd(usd), unpriced_count=0)


def _project(name, *, completed=1, abandoned=0, usd=1.0, delivered=(), fixed=(), improved=()):
    return ProjectReport(
        project=name, completed=completed, abandoned=abandoned, spend=_cost(usd),
        delivered=tuple(delivered), fixed=tuple(fixed), improved=tuple(improved),
    )


def _response(**overrides):
    fields = dict(
        day=datetime.date(2026, 10, 24), completed=0, abandoned=0, spend=_cost(0),
        automation_count=0, automation_spend=_cost(0), cache_hit_rate=None,
        backlog_start=0, backlog_close=0, backlog_delta=0,
        summary=None, projects=(), summary_unmatched=None,
    )
    fields.update(overrides)
    return ReportResponse(**fields)


EMPTY_TOP = "0 items closed · not recorded spent · n/a cache hit · 0 automation items (not recorded) · backlog 0 → 0 (+0)"


class TestReportMarkdown(unittest.TestCase):
    def test_the_agreed_example_renders_whole(self):
        response = _response(
            completed=8, abandoned=1, spend=_cost(3.92), automation_count=4, automation_spend=_cost(0.61), cache_hit_rate=0.921,
            backlog_start=42, backlog_close=37, backlog_delta=-5,
            projects=(
                _project(
                    "lightcycle", completed=5, usd=2.12,
                    fixed=("- The mutation report now refuses stale results [LC-1339]",),
                    improved=("- A review-ci step carries a reason [LC-1337, LC-1338]",),
                ),
                _project("flynns-workflows", completed=3, usd=1.80, fixed=("- kb-check reads angle links [FW-28]",)),
            ),
            summary_unmatched="Loose line [XX-1]",
        )

        self.assertEqual(
            report_markdown(response),
            "# Saturday 24 October 2026\n\n"
            "9 items closed · $3.92 spent · 92.1% cache hit · 4 automation items ($0.61) · backlog 42 → 37 (-5)\n\n"
            "## lightcycle\n\n"
            "5 closed · $2.12\n\n"
            "### Fixed\n\n"
            "- The mutation report now refuses stale results (LC-1339)\n\n"
            "### Improved\n\n"
            "- A review-ci step carries a reason (LC-1337, LC-1338)\n\n"
            "## flynns-workflows\n\n"
            "3 closed · $1.80\n\n"
            "### Fixed\n\n"
            "- kb-check reads angle links (FW-28)\n\n"
            "## Not matched to a project\n\n"
            "Loose line [XX-1]\n",
        )

    def test_a_day_with_nothing_closed_is_the_title_and_top_line_only(self):
        self.assertEqual(
            report_markdown(_response()),
            "# Saturday 24 October 2026\n\n%s\n" % EMPTY_TOP,
        )

    def test_a_project_with_no_bullets_is_its_heading_and_stats_only(self):
        text = report_markdown(_response(projects=(_project("yori"),)))

        self.assertTrue(text.endswith("## yori\n\n1 closed · $1.00\n"))

    def test_the_categories_come_in_delivered_fixed_improved_order(self):
        text = report_markdown(_response(projects=(
            _project("yori", improved=("- c",), fixed=("- b",), delivered=("- a",)),
        )))

        self.assertLess(text.index("### Delivered"), text.index("### Fixed"))
        self.assertLess(text.index("### Fixed"), text.index("### Improved"))

    def test_no_project_renders_under_its_own_heading(self):
        text = report_markdown(_response(projects=(_project(None),)))

        self.assertIn("\n## No project\n", text)

    def test_ids_are_parenthesised_only_for_the_trailing_group(self):
        bullets = (
            "- One [A-1]",
            "- Two [A-1, A-2].",
            "- Space [A-1 A-2]",
            "- No ids here",
            "- mid [X] then text [LC-1]",
            "- Both [LC-1337, LC-1338].",
        )

        text = report_markdown(_response(projects=(_project("yori", fixed=bullets),)))

        self.assertIn(
            "- One (A-1)\n"
            "- Two (A-1, A-2).\n"
            "- Space (A-1, A-2)\n"
            "- No ids here\n"
            "- mid [X] then text (LC-1)\n"
            "- Both (LC-1337, LC-1338).\n",
            text,
        )

    def test_singular_forms(self):
        response = _response(completed=1, automation_count=1)

        self.assertIn("1 item closed · ", report_markdown(response))
        self.assertIn(" · 1 automation item (", report_markdown(response))

    def test_no_tokens_reads_na_cache_hit(self):
        self.assertIn(" · n/a cache hit · ", report_markdown(_response()))

    def test_a_positive_delta_carries_a_plus_sign(self):
        text = report_markdown(_response(backlog_start=1, backlog_close=4, backlog_delta=3))

        self.assertIn("backlog 1 → 4 (+3)", text)

    def test_unmatched_text_is_the_last_section_and_verbatim(self):
        text = report_markdown(_response(
            projects=(_project("yori"),), summary_unmatched="Line [A-1]\n- bullet [B-2]",
        ))

        self.assertTrue(text.endswith("## Not matched to a project\n\nLine [A-1]\n- bullet [B-2]\n"))

    def test_no_unmatched_heading_when_there_is_no_remainder(self):
        self.assertNotIn("Not matched", report_markdown(_response(projects=(_project("yori"),))))

    def test_no_bullet_the_splitter_attributed_still_ends_in_a_bracket(self):
        summary = (
            "Delivered\n- Shipped a [LC-1]\n- Shipped b [LC-2, LC-3].\n\n"
            "Fixed\n- Repaired c [LC-4]\n- Stray with no id\n"
        )
        sections, unmatched = split_summary(summary, {"LC-1": "yori", "LC-2": "yori", "LC-3": "yori", "LC-4": "yori"})
        project = _project(
            "yori", delivered=sections["yori"]["Delivered"], fixed=sections["yori"]["Fixed"],
        )

        text = report_markdown(_response(projects=(project,), summary_unmatched=unmatched))
        bullets = [line for line in text.split("## Not matched")[0].splitlines() if line.startswith("- ")]

        self.assertEqual(len(bullets), 3)
        self.assertFalse(any(line.rstrip(".;, ").endswith("]") for line in bullets))
        self.assertIn("- Shipped b (LC-2, LC-3).", bullets)
