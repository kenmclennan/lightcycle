from tests.support.fake_github_budget import FakeGithubBudget
import unittest

from lightcycle.application.inspect import DoctorInput, DoctorUseCase
from lightcycle.domain.guidance.conventions import CONVENTIONS_VERSION
from lightcycle.domain.pool import GuidanceSyncState
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_machine import FakeMachine
from tests.support.fake_store import FakeStore
from tests.support.installed_steps import AGENT, HUMAN, SCRIPT, graph, installed
from tests.support.tui_harness import FakeConfigReloadStatus, FakeGuidanceSyncStatus, FakeLock
from tests.unit.test_doctor import (
    _ALL_KEYS, FakeWorkflowBundle, FakeWorkflowSource, _Worktrees, _cfg,
)
from tests.unit.test_select_guidance import _entry


def _problems(files, projects=(), budget=None, git=None, status=None, origins=None, kind=None):
    files = {"CONVENTIONS.md": _conventions(CONVENTIONS_VERSION), **files}
    store = FakeStore()
    store.add_project("guidance", shortcode="GDN", local_path="/kb")
    for identity, facets in projects:
        store.add_project(identity, facets=facets)
    fs = FakeFs(dirs={"/kb": []})
    if git is None:
        git = FakeGit(ref="origin/main", ref_files={"origin/main": dict(files)})
    keys = dict(_ALL_KEYS)
    if budget is not None:
        keys["guidance_budget_bytes"] = budget
    source, bundle = FakeWorkflowSource(), FakeWorkflowBundle()
    source.add_bundle("acme", "sha1", 1, current=True)
    if origins is not None:
        source, bundle = installed(origins)
    report = DoctorUseCase(
        store, source, _cfg(**keys), bundle, fs, FakeMachine(), _Worktrees(),
        git, status if status is not None else FakeGuidanceSyncStatus(), FakeConfigReloadStatus(), FakeLock(running=False), FakeGithubBudget()).execute(DoctorInput())
    if kind is not None:
        return [p for p in report.problems["guidance"] if p.kind == kind]
    return [
        p.message for p in report.problems["guidance"]
        if p.kind not in ("guidance-entries-nonconforming", "guidance-budget-overflow")
    ]


_KIND = "guidance-budget-overflow"
_ORIGINS = {"acme": ("sha1", {
    "write-code": AGENT, "other-agent": AGENT, "script-step": SCRIPT, "human-step": HUMAN,
}, {"wf": graph(
    ("write-code", "done", "other-agent"), ("other-agent", "done", "script-step"),
    ("script-step", "done", "human-step"))})}


def _problem_objects(files):
    store = FakeStore()
    store.add_project("guidance", shortcode="GDN", local_path="/kb")
    source = FakeWorkflowSource()
    source.add_bundle("acme", "sha1", 1, current=True)
    git = FakeGit(ref="origin/main", ref_files={"origin/main": dict(files)})
    report = DoctorUseCase(
        store, source, _cfg(**_ALL_KEYS), FakeWorkflowBundle(), FakeFs(dirs={"/kb": []}),
        FakeMachine(), _Worktrees(), git, FakeGuidanceSyncStatus(), FakeConfigReloadStatus(), FakeLock(running=False), FakeGithubBudget()).execute(DoctorInput())
    return report.problems["guidance"]


def _of_kind(files, kind):
    return [p for p in _problem_objects(files) if p.kind == kind]


def _conventions(version):
    return ("# Conventions\n\nConventions version: %s\n" % version).encode()


_NO_WHY = _entry().replace(b"why: y\n", b"")
_NO_PURPOSE = _entry().replace(b"purpose: p\n", b"")


class TestDoctorConventionsVersion(unittest.TestCase):
    def test_version_four_is_outdated_and_version_five_is_not(self):
        self.assertEqual(
            len(_of_kind({"CONVENTIONS.md": _conventions(4)}, "guidance-conventions-outdated")), 1)
        self.assertEqual(
            _of_kind({"CONVENTIONS.md": _conventions(5)}, "guidance-conventions-outdated"), [])

    def test_an_older_version_is_reported_naming_both_and_the_pr(self):
        found = _of_kind({"CONVENTIONS.md": _conventions(CONVENTIONS_VERSION - 1)},
                         "guidance-conventions-outdated")
        self.assertEqual(len(found), 1)
        self.assertIn(str(CONVENTIONS_VERSION - 1), found[0].message)
        self.assertIn(str(CONVENTIONS_VERSION), found[0].message)
        self.assertIn("PR", found[0].fix)

    def test_the_current_and_a_newer_version_report_nothing(self):
        for version in (CONVENTIONS_VERSION, CONVENTIONS_VERSION + 1):
            self.assertEqual(
                _of_kind({"CONVENTIONS.md": _conventions(version)}, "guidance-conventions-outdated"),
                [])

    def test_a_file_with_no_version_line_records_version_zero(self):
        found = _of_kind({"CONVENTIONS.md": b"# Conventions\n"}, "guidance-conventions-outdated")
        self.assertEqual(len(found), 1)
        self.assertIn("version 0", found[0].message)

    def test_an_absent_file_records_version_zero(self):
        found = _of_kind({"a.md": _entry()}, "guidance-conventions-outdated")
        self.assertEqual(len(found), 1)
        self.assertIn("version 0", found[0].message)

    def test_an_unreadable_file_is_a_kindless_problem_not_outdated(self):
        problems = _problem_objects({"CONVENTIONS.md": b"\xff\xfe"})
        self.assertEqual([p for p in problems if p.kind == "guidance-conventions-outdated"], [])
        self.assertTrue(any("cannot be read" in p.message and p.kind is None for p in problems))


class TestDoctorNonconformingEntries(unittest.TestCase):
    def _files(self, **extra):
        files = {"CONVENTIONS.md": _conventions(CONVENTIONS_VERSION)}
        files.update(extra)
        return files

    def test_mixed_repo_counts_exactly_the_failing_files(self):
        found = _of_kind(
            self._files(**{"lacks-purpose.md": _NO_PURPOSE, "lacks-why.md": _NO_WHY,
                           "fine.md": _entry()}),
            "guidance-entries-nonconforming")
        self.assertEqual(len(found), 1)
        self.assertIn("2 guidance entries", found[0].message)
        self.assertIn("lacks-purpose.md", found[0].message)
        self.assertIn("lacks-why.md", found[0].message)
        self.assertNotIn("fine.md", found[0].message)
        self.assertIn("guidance-entry", found[0].fix)

    def test_all_conforming_reports_nothing(self):
        self.assertEqual(
            _of_kind(self._files(**{"a.md": _entry(), "b.md": _entry()}),
                     "guidance-entries-nonconforming"), [])

    def test_none_conforming_reports_the_full_count(self):
        found = _of_kind(
            self._files(**{"a.md": _NO_WHY, "b.md": _NO_WHY, "c.md": _NO_PURPOSE}),
            "guidance-entries-nonconforming")
        self.assertIn("3 guidance entries", found[0].message)

    def test_more_than_five_names_five_and_the_rest(self):
        files = self._files(**{"e%d.md" % i: _NO_WHY for i in range(7)})
        (found,) = _of_kind(files, "guidance-entries-nonconforming")
        self.assertIn("7 guidance entries", found.message)
        self.assertIn("e4.md and 2 more", found.message)
        self.assertNotIn("e5.md", found.message)

    def test_a_concept_page_never_counts(self):
        found = _of_kind(self._files(**{"kotlin.md": b"# kotlin\n"}),
                         "guidance-entries-nonconforming")
        self.assertEqual(found, [])

    def test_a_current_repo_is_clean(self):
        self.assertEqual(_problem_objects(self._files(**{"a.md": _entry()})), [])


class TestDoctorGuidance(unittest.TestCase):
    def test_a_failed_fetch_is_reported_with_its_detail(self):
        status = FakeGuidanceSyncStatus(GuidanceSyncState(
            ok=False, at=1000.0, detail="could not resolve host", ref="origin/main"))
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
            _Worktrees(), FakeGit(), FakeGuidanceSyncStatus(), FakeConfigReloadStatus(), FakeLock(running=False), FakeGithubBudget()).execute(DoctorInput())
        self.assertEqual(report.problems["guidance"], [])
        store.add_project("guidance", shortcode="GDN", local_path="/gone")
        report = DoctorUseCase(
            store, source, _cfg(**_ALL_KEYS), FakeWorkflowBundle(), FakeFs(), FakeMachine(),
            _Worktrees(), FakeGit(), FakeGuidanceSyncStatus(), FakeConfigReloadStatus(), FakeLock(running=False), FakeGithubBudget()).execute(DoctorInput())
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

    def test_stable_entry_without_verified_is_not_reported(self):
        self.assertEqual(_problems({"a.md": _entry(verified=None)}), [])

    def test_a_guidance_project_without_a_shortcode_yields_one_finding_with_the_fix(self):
        store = FakeStore()
        store.add_project("guidance", local_path="/kb")
        found = self._shortcode_findings(store, _ALL_KEYS)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, "guidance-shortcode-missing")
        self.assertIn("lc project set guidance --shortcode GDN", found[0].fix)

    def test_no_shortcode_finding_with_a_shortcode_unregistered_or_key_absent(self):
        with_code = FakeStore()
        with_code.add_project("guidance", shortcode="GDN", local_path="/kb")
        self.assertEqual(self._shortcode_findings(with_code, _ALL_KEYS), [])
        self.assertEqual(self._shortcode_findings(FakeStore(), _ALL_KEYS), [])
        bare = FakeStore()
        bare.add_project("guidance", local_path="/kb")
        keys = {k: v for k, v in _ALL_KEYS.items() if k != "guidance_shortcode"}
        self.assertEqual(self._shortcode_findings(bare, keys), [])

    def _shortcode_findings(self, store, keys):
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        report = DoctorUseCase(
            store, source, _cfg(**keys), FakeWorkflowBundle(), FakeFs(), FakeMachine(),
            _Worktrees(), FakeGit(), FakeGuidanceSyncStatus(), FakeConfigReloadStatus(),
            FakeLock(running=False), FakeGithubBudget()).execute(DoctorInput())
        return [p for p in report.problems["guidance"] if p.kind == "guidance-shortcode-missing"]

    def test_draft_without_verified_is_not_reported(self):
        self.assertEqual(_problems({"a.md": _entry(status="draft", verified=None)}), [])

    def test_overflow_reports_project_step_total_and_skipped_ids(self):
        files = {
            "a.md": _entry(steps=["write-code"], body="x" * 60),
            "b.md": _entry(steps=["write-code"], body="x" * 60),
            "c.md": _entry(body="x" * 10),
        }
        found = _problems(files, [("acme/x", ())], budget="100", origins=_ORIGINS, kind=_KIND)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, "guidance-budget-overflow")
        self.assertIn("project acme/x", found[0].message)
        self.assertIn("step acme/write-code", found[0].message)
        self.assertIn("matches 130 bytes", found[0].message)
        self.assertIn("(100)", found[0].message)
        self.assertTrue(found[0].message.endswith("delivery skips: b"))
        for remedy in ("narrow", "consolidate", "deprecate"):
            self.assertIn(remedy, found[0].fix)
        self.assertNotIn("raise", found[0].fix)

    def test_unscoped_overflow_is_reported_at_every_agent_step(self):
        files = {"a.md": _entry(body="x" * 60), "b.md": _entry(body="x" * 60)}
        found = _problems(files, [("acme/x", ())], budget="100", origins=_ORIGINS, kind=_KIND)
        self.assertEqual(
            sorted(p.message.split("step ")[1].split(" ")[0] for p in found),
            ["acme/other-agent", "acme/write-code"])

    def test_one_overflowing_pair_among_four_yields_one_problem(self):
        files = {
            "a.md": _entry(facets=["python"], steps=["write-code"], body="x" * 60),
            "b.md": _entry(facets=["python"], steps=["write-code"], body="x" * 60),
            "python.md": b"",
        }
        found = _problems(
            files, [("py/x", ("python",)), ("kt/x", ("kotlin",))], budget="100",
            origins=_ORIGINS, kind=_KIND)
        self.assertEqual(len(found), 1)
        self.assertIn("project py/x", found[0].message)

    def test_a_script_stage_never_yields_a_problem(self):
        files = {"a.md": _entry(body="x" * 60), "b.md": _entry(body="x" * 60)}
        found = _problems(files, [("acme/x", ())], budget="100", origins=_ORIGINS, kind=_KIND)
        self.assertFalse(any("script-step" in p.message for p in found))
        self.assertFalse(any("human-step" in p.message for p in found))

    def test_entries_for_other_facets_do_not_overflow_a_project(self):
        files = {"a.md": _entry(facets=["python"], body="x" * 600), "python.md": b""}
        self.assertEqual(_problems(files, [("acme/x", ("kotlin",))], budget="100"), [])


class TestDoctorRevertedEntry(unittest.TestCase):
    def _found(self, head, history):
        files = {"CONVENTIONS.md": _conventions(CONVENTIONS_VERSION), "a.md": head}
        ref_files = {"origin/main": files}
        for sha, content in history.items():
            ref_files[sha] = {"a.md": content}
        git = FakeGit(ref="origin/main", ref_files=ref_files, history={"a.md": list(history)})
        store = FakeStore()
        store.add_project("guidance", shortcode="GDN", local_path="/kb")
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        report = DoctorUseCase(
            store, source, _cfg(**_ALL_KEYS), FakeWorkflowBundle(), FakeFs(dirs={"/kb": []}),
            FakeMachine(), _Worktrees(), git, FakeGuidanceSyncStatus(), FakeConfigReloadStatus(),
            FakeLock(running=False), FakeGithubBudget()).execute(DoctorInput())
        return [p for p in report.problems["guidance"] if p.kind == "guidance-entry-reverted"]

    def test_stable_then_draft_is_flagged_with_the_reverting_commit(self):
        draft, stable = _entry(status="draft"), _entry()
        found = self._found(draft, {"c3": draft, "c2": draft, "c1": stable, "c0": stable})
        self.assertEqual(len(found), 1)
        self.assertIn("a", found[0].message)
        self.assertIn("c2", found[0].message)
        self.assertNotIn("c3", found[0].message)
        self.assertIn("guidance-entry", found[0].fix)
        self.assertIn("restore a to stable", found[0].fix)
        self.assertNotIn("verify", found[0].fix)

    def test_draft_only_is_not_flagged(self):
        draft = _entry(status="draft")
        self.assertEqual(self._found(draft, {"c1": draft, "c0": draft}), [])

    def test_stable_then_stable_is_not_flagged(self):
        stable = _entry()
        self.assertEqual(self._found(stable, {"c1": stable, "c0": stable}), [])


if __name__ == "__main__":
    unittest.main()
