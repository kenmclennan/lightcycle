import unittest

from lightcycle.application.inspect import DoctorInput, DoctorUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_machine import FakeMachine
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeGuidanceSyncStatus
from tests.unit.test_doctor import (
    _ALL_KEYS, FakeWorkflowBundle, FakeWorkflowSource, _Worktrees, _cfg,
)
from tests.unit.test_select_guidance import _entry


def _problems(files, projects=(), budget=None, git=None, status=None):
    store = FakeStore()
    store.add_project("guidance", local_path="/kb")
    for identity, facets in projects:
        store.add_project(identity, facets=facets)
    fs = FakeFs(dirs={"/kb": []})
    if git is None:
        git = FakeGit(ref="origin/main", ref_files={"origin/main": dict(files)})
    keys = dict(_ALL_KEYS)
    if budget is not None:
        keys["guidance_budget_bytes"] = budget
    source = FakeWorkflowSource()
    source.add_bundle("acme", "sha1", 1, current=True)
    report = DoctorUseCase(
        store, source, _cfg(**keys), FakeWorkflowBundle(), fs, FakeMachine(), _Worktrees(),
        git, status if status is not None else FakeGuidanceSyncStatus(),
    ).execute(DoctorInput())
    return [p.message for p in report.problems["guidance"]]


class TestDoctorGuidance(unittest.TestCase):
    def test_a_failed_fetch_is_reported_with_its_detail(self):
        status = FakeGuidanceSyncStatus(
            {"ok": False, "at": 1000.0, "detail": "could not resolve host", "ref": "origin/main"})
        msgs = _problems({"a.md": _entry()}, status=status)
        self.assertEqual(len(msgs), 1)
        self.assertIn("fetch failed", msgs[0])
        self.assertIn("could not resolve host", msgs[0])
        self.assertIn("origin/main", msgs[0])

    def test_no_status_record_is_not_a_problem(self):
        self.assertEqual(_problems({"a.md": _entry()}), [])

    def test_an_origin_never_fetched_is_one_problem(self):
        git = FakeGit(origin="git@x:kb.git", ref=None)
        msgs = _problems({}, git=git)
        self.assertEqual(len(msgs), 1)
        self.assertIn("never been fetched", msgs[0])

    def test_clean_repo_has_no_problems(self):
        files = {"a.md": _entry(facets=["kotlin"]), "kotlin.md": b"# kotlin\n"}
        self.assertEqual(_problems(files, [("acme/x", ("kotlin",))]), [])

    def test_unregistered_or_missing_repo_is_left_to_the_facets_category(self):
        store = FakeStore()
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        report = DoctorUseCase(
            store, source, _cfg(**_ALL_KEYS), FakeWorkflowBundle(), FakeFs(), FakeMachine(),
            _Worktrees(), FakeGit(), FakeGuidanceSyncStatus(),
        ).execute(DoctorInput())
        self.assertEqual(report.problems["guidance"], [])
        store.add_project("guidance", local_path="/gone")
        report = DoctorUseCase(
            store, source, _cfg(**_ALL_KEYS), FakeWorkflowBundle(), FakeFs(), FakeMachine(),
            _Worktrees(), FakeGit(), FakeGuidanceSyncStatus(),
        ).execute(DoctorInput())
        self.assertEqual(report.problems["guidance"], [])

    def test_malformed_entries_are_reported_by_id(self):
        files = {
            "no-applies.md": b"---\ntype: Guidance\nstatus: stable\nverified: k\n---\nb\n",
            "block.md": b"---\ntype: Guidance\nstatus: stable\nverified: k\napplies-to:\n  facets:\n---\nb\n",
            "unclosed.md": b"---\ntype: Guidance\n",
        }
        msgs = _problems(files)
        self.assertEqual(len(msgs), 3)
        for name in ("no-applies", "block", "unclosed"):
            self.assertTrue(any("entry %s " % name in m for m in msgs), name)

    def test_facet_without_a_concept_page_is_reported(self):
        msgs = _problems({"a.md": _entry(facets=["kotlin", "spring"]), "kotlin.md": b""})
        self.assertEqual(len(msgs), 1)
        self.assertIn("entry a applies to facet spring", msgs[0])

    def test_stable_entry_without_verified_is_reported(self):
        msgs = _problems({"a.md": _entry(verified=None)})
        self.assertEqual(len(msgs), 1)
        self.assertIn("entry a is stable but has no verified", msgs[0])

    def test_draft_without_verified_is_not_reported(self):
        self.assertEqual(_problems({"a.md": _entry(status="draft", verified=None)}), [])

    def test_budget_overflow_names_project_step_and_ids(self):
        files = {
            "a.md": _entry(steps=["write-code"], body="x" * 60),
            "b.md": _entry(steps=["write-code"], body="x" * 60),
            "c.md": _entry(body="x" * 10),
        }
        msgs = _problems(files, [("acme/x", ())], budget="100")
        self.assertEqual(len(msgs), 1)
        self.assertIn("project acme/x", msgs[0])
        self.assertIn("write-code", msgs[0])
        self.assertIn("exceed guidance-budget-bytes (100)", msgs[0])
        self.assertTrue(msgs[0].endswith("b - shorten them or raise the budget"))

    def test_overflow_with_no_step_entries_names_any_step(self):
        files = {"a.md": _entry(body="x" * 60), "b.md": _entry(body="x" * 60)}
        msgs = _problems(files, [("acme/x", ())], budget="100")
        self.assertEqual(len(msgs), 1)
        self.assertIn("for any step", msgs[0])

    def test_entries_for_other_facets_do_not_overflow_a_project(self):
        files = {"a.md": _entry(facets=["python"], body="x" * 600), "python.md": b""}
        self.assertEqual(_problems(files, [("acme/x", ("kotlin",))], budget="100"), [])


if __name__ == "__main__":
    unittest.main()
